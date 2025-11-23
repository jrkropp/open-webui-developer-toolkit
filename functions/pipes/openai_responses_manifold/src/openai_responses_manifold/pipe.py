"""Open WebUI pipe entrypoint for the OpenAI Responses manifold."""

from __future__ import annotations

import inspect
import logging
from typing import Any, Iterable

from openai_responses_manifold.core.config import PipeValves, UserValves, merge_valves
from openai_responses_manifold.core.logging import logging_context
from openai_responses_manifold.domain import (
    ResponsesEngine,
    ToolPolicy,
    build_web_search_tools,
    route_auto_model,
)
from openai_responses_manifold.domain.history import HistoryManager
from openai_responses_manifold.openai_api import OpenAIClient
from openai_responses_manifold.openwebui import (
    OpenWebUIHistoryStore,
    OpenWebUIRuntimeEvents,
    OpenWebUIToolExecutor,
    OpenWebUIToolRegistry,
    build_mcp_tools,
    build_turn_context,
    map_completions_to_responses,
)


class Pipe:
    """Open WebUI pipe implementation for the Responses manifold."""

    id = "openai_responses"

    class Valves(PipeValves):
        pass

    class UserValves(UserValves):
        pass

    def __init__(self) -> None:
        self.valves = self.Valves()
        self.client = OpenAIClient()
        self.history_store = OpenWebUIHistoryStore()
        self.history_manager = HistoryManager(self.history_store)
        self.engine = ResponsesEngine(self.client, self.history_manager)

    @staticmethod
    def _status_unclamp_script() -> str:
        return """
        (() => {
        if (document.getElementById("owui-status-unclamp")) return "ok";
        const style = document.createElement("style");
        style.id = "owui-status-unclamp";
        style.textContent = `
            .status-description .line-clamp-1,
            .status-description .text-base.line-clamp-1,
            .status-description .text-gray-500.text-base.line-clamp-1 {
            display: block !important;
            overflow: visible !important;
            -webkit-line-clamp: unset !important;
            -webkit-box-orient: initial !important;
            white-space: pre-wrap !important;
            word-break: break-word;
            }

            .status-description .text-base::first-line,
            .status-description .text-gray-500.text-base::first-line {
            font-weight: 500 !important;
            }
        `;

        document.head.appendChild(style);
        return "ok";
        })();
        """

    async def _maybe_unclamp_status(self, event_call: Any | None) -> None:
        if not event_call:
            return
        payload = {"type": "execute", "data": {"code": self._status_unclamp_script()}}
        try:
            result = event_call(payload)
            if inspect.isawaitable(result):
                await result
        except Exception:
            return

    async def pipes(self) -> list[dict[str, Any]]:
        cfg = self.valves
        ids = [m.strip() for m in (cfg.MODEL_ID or "").split(",") if m.strip()]
        return [{"id": model_id, "name": f"OpenAI Responses: {model_id}"} for model_id in ids]

    async def _resolve_tools(self, __tools__: Any) -> Any:
        if inspect.isawaitable(__tools__):
            return await __tools__
        return __tools__

    async def pipe(
        self,
        body: dict[str, Any] | None = None,
        __user__: dict[str, Any] | None = None,
        __assistant__: dict[str, Any] | None = None,
        __event_emitter__: Any | None = None,
        __event_call__: Any | None = None,
        __tools__: Iterable[Any] | None = None,
        __tasks__: Iterable[Any] | None = None,
        __task__: Any | None = None,
        __task_body__: dict[str, Any] | None = None,
        __metadata__: dict[str, Any] | None = None,
    ) -> Any:
        body = body or {}
        pipe_valves = self.valves
        user_valves = self.UserValves.model_validate((__user__ or {}).get("valves") or {})
        cfg = merge_valves(pipe_valves, user_valves)

        events = OpenWebUIRuntimeEvents(__event_emitter__)
        level = getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO)

        with logging_context(
            (__metadata__ or {}).get("session_id"),
            level,
            chat_id=(__metadata__ or {}).get("chat_id"),
            message_id=(__metadata__ or {}).get("message_id"),
            user_id=(__user__ or {}).get("id"),
        ):
            await self._maybe_unclamp_status(__event_call__)
            ctx = build_turn_context(
                pipe_valves=pipe_valves,
                user_valves=user_valves,
                runtime_cfg=cfg,
                __user__=__user__,
                __metadata__=__metadata__,
            )
            history_key = {"chat_id": (__metadata__ or {}).get("chat_id"), "pipe_id": self.id}
            resolved_tools = await self._resolve_tools(__tools__ or {})
            registry = OpenWebUIToolRegistry(resolved_tools)
            executor = OpenWebUIToolExecutor(resolved_tools)

            if __task__ is not None:
                task_body = __task_body__ if __task_body__ is not None else body or {}
                request = map_completions_to_responses(
                    body=task_body, ctx=ctx, history_manager=self.history_manager, history_key=history_key
                )[0]
                request.stream = False
                request.store = False
                request.tools = None
                request.include = None
                return await self.engine.run_task(request, ctx)

            if body.get("stream") is False:
                await events.notification("Non-streaming chat is not supported by this manifold.", level="error")
                await events.chat_completion({"done": True, "error": "Streaming required"})
                return ""

            request, base_tools, extra_tools = map_completions_to_responses(
                body=body, ctx=ctx, history_manager=self.history_manager, history_key=history_key
            )

            mcp_tools = build_mcp_tools(cfg)
            web_search_tools = build_web_search_tools(
                model_id=ctx.model_id, features=ctx.features, cfg=cfg
            )
            tools_for_responses = ToolPolicy.build_responses_tools(
                model_id=ctx.model_id,
                features=ctx.features,
                cfg=cfg,
                registry=registry,
                body_tools=base_tools,
                extra_tools=extra_tools,
                mcp_tools=mcp_tools,
                web_search_tools=web_search_tools,
            )
            if tools_for_responses:
                request.tools = tools_for_responses

            request.truncation = cfg.TRUNCATION
            request.prompt_cache_key = cfg.PROMPT_CACHE_KEY

            if "reasoning_summary" in ctx.features and cfg.REASONING_SUMMARY != "disabled":
                request.reasoning = request.reasoning or {}
                request.reasoning["summary"] = cfg.REASONING_SUMMARY

            if "reasoning" in ctx.features and cfg.PERSIST_REASONING_TOKENS != "disabled":
                request.include = list(request.include or [])
                if "reasoning.encrypted_content" not in request.include:
                    request.include.append("reasoning.encrypted_content")

            if any(t.get("type") == "web_search" for t in (request.tools or [])):
                request.include = list(request.include or [])
                if "web_search_call.action.sources" not in request.include:
                    request.include.append("web_search_call.action.sources")

            owui_model_id = (ctx.metadata.get("owui_model_id") or "").lower()
            if owui_model_id.endswith(".gpt-5-auto") or owui_model_id.endswith(".gpt-5-auto-dev"):
                request = await route_auto_model(
                    client=self.client, request=request, ctx=ctx, tools=request.tools or [], events=events
                )

            result = await self.engine.run_streaming_turn(
                request=request,
                ctx=ctx,
                events=events,
                history_key=history_key,
                tool_executor=executor,
            )

            if result.citations and (__metadata__ or {}).get("chat_id") and (__metadata__ or {}).get("message_id"):
                try:
                    from open_webui.models.chats import Chats

                    Chats.upsert_message_to_chat_by_id_and_message_id(
                        (__metadata__ or {}).get("chat_id"),
                        (__metadata__ or {}).get("message_id"),
                        {
                            "sources": [
                                {
                                    "source": {"name": c.source_name, "url": c.url},
                                    "document": c.document,
                                    "metadata": [c.metadata],
                                }
                                for c in result.citations
                            ]
                        },
                    )
                except Exception:
                    pass

            return result.text


__all__ = ["Pipe"]
