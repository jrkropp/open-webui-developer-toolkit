"""Open WebUI pipe implementation that delegates to the Responses engine."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from open_webui.models.models import ModelForm, Models

from .core.api_models import CompletionsBody, ResponsesBody
from .core.capabilities import supports
from .engine import EventEmitter, ResponsesEngine
from .infra import ItemStore, OpenAIResponsesClient
from .logging_config import reset_session, set_session
from .services import HistoryBuilder, build_tools, route_auto_model
from .settings import PipeValves, UserValves
from .utils import SessionLogger


class Pipe:
    class Valves(PipeValves):
        """Admin-level valve configuration."""

    class UserValves(UserValves):
        """Per-user valve overrides."""

    def __init__(self) -> None:
        self.type = "manifold"
        self.id = "openai_responses"
        self.valves = self.Valves()
        self.logger = SessionLogger.get_logger(__name__)
        self.store = ItemStore()
        self.engine = ResponsesEngine(
            client=OpenAIResponsesClient(),
            item_store=self.store,
            logger=self.logger,
        )

    async def pipes(self) -> list[dict[str, str]]:
        model_ids = [
            model_id.strip() for model_id in self.valves.MODEL_ID.split(",") if model_id.strip()
        ]
        return [{"id": model_id, "name": f"OpenAI: {model_id}"} for model_id in model_ids]

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Request,
        __event_emitter__: EventEmitter,
        __event_call__: Callable[[dict[str, Any]], Awaitable[Any]] | None,
        __metadata__: dict[str, Any],
        __tools__: list[dict[str, Any]] | dict[str, Any] | None,
        __task__: dict[str, Any] | None = None,
        __task_body__: dict[str, Any] | None = None,
    ) -> Awaitable[str] | str | None:
        valves = self._merge_valves(
            self.valves, self.UserValves.model_validate(__user__.get("valves", {}))
        )
        openwebui_model_id = __metadata__.get("model", {}).get("id", "")
        user_identifier = __user__[valves.PROMPT_CACHE_KEY]
        features = __metadata__.get("features", {}).get("openai_responses", {})

        tokens = set_session(
            __metadata__.get("session_id"),
            getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO),
        )

        if __event_call__:
            await __event_call__(self._status_unclamp_script())

        completions_body = CompletionsBody.model_validate(body)
        history_input = self._build_history_input(
            completions_body.messages,
            __metadata__,
        )
        extra_params: dict[str, Any] = {
            "truncation": valves.TRUNCATION,
            "user": user_identifier,
        }
        chat_id_value = __metadata__.get("chat_id")
        if isinstance(chat_id_value, str):
            extra_params["chat_id"] = chat_id_value
        if valves.MAX_TOOL_CALLS is not None:
            extra_params["max_tool_calls"] = valves.MAX_TOOL_CALLS

        responses_body = ResponsesBody.from_completions(
            completions_body=completions_body,
            history_input=history_input,
            **extra_params,
        )

        if __task__:
            self.logger.info("Detected task model: %s", __task__)
            return await self.engine.run_task_model(responses_body.model_dump(), valves)

        __tools__ = await __tools__ if inspect.isawaitable(__tools__) else __tools__
        tool_registry: dict[str, dict[str, Any]] | None = (
            __tools__ if isinstance(__tools__, dict) else None
        )
        tools = build_tools(
            responses_body,
            valves,
            openwebui_tools=tool_registry,
            features=features,
            extra_tools=getattr(completions_body, "extra_tools", None),
        )

        if tools and supports("function_calling", responses_body.model):
            model = Models.get_model_by_id(openwebui_model_id)
            if model:
                params = dict(model.params or {})
                if params.get("function_calling") != "native":
                    await self.engine.emit_notification(
                        __event_emitter__,
                        content=f"Enabling native function calling for model: {openwebui_model_id}. Please re-run your query.",
                        level="info",
                    )
                    params["function_calling"] = "native"
                    form_data = model.model_dump()
                    form_data["params"] = params
                    Models.update_model_by_id(openwebui_model_id, ModelForm(**form_data))

        if openwebui_model_id.endswith(".gpt-5-auto-dev"):
            responses_body = await route_auto_model(
                self.engine.client,
                router_model="gpt-4.1-mini",
                responses_body=responses_body,
                valves=valves,
                tools=tools,
                event_emitter=__event_emitter__,
            )
        elif openwebui_model_id.endswith(".gpt-5-auto"):
            responses_body.model = "gpt-5-chat-latest"
            await self.engine.emit_notification(
                __event_emitter__,
                content="Model router coming soon — using gpt-5-chat-latest (GPT-5 Fast).",
                level="warning",
            )

        if supports("function_calling", responses_body.model):
            responses_body.tools = tools

        if (
            supports("reasoning_summary", responses_body.model)
            and valves.REASONING_SUMMARY != "disabled"
        ):
            reasoning_params = dict(responses_body.reasoning or {})
            reasoning_params["summary"] = valves.REASONING_SUMMARY
            responses_body.reasoning = reasoning_params

        if (
            supports("reasoning", responses_body.model)
            and valves.PERSIST_REASONING_TOKENS != "disabled"
            and responses_body.store is False
        ):
            responses_body.include = responses_body.include or []
            if "reasoning.encrypted_content" not in responses_body.include:
                responses_body.include.append("reasoning.encrypted_content")

        if any(
            isinstance(tool, dict) and tool.get("type") == "web_search"
            for tool in (responses_body.tools or [])
        ):
            responses_body.parallel_tool_calls = False
        else:
            responses_body.parallel_tool_calls = getattr(valves, "PARALLEL_TOOL_CALLS", True)

        try:
            return await self.engine.run_streaming_turn(
                responses_body,
                valves=valves,
                metadata=__metadata__,
                event_emitter=__event_emitter__,
                tool_registry=tool_registry or {},
            )
        finally:
            reset_session(tokens)

    def _merge_valves(self, pipe_valves: PipeValves, user_valves: UserValves) -> PipeValves:
        merged = pipe_valves.model_copy(deep=True)
        if user_valves.LOG_LEVEL != "INHERIT":
            merged.LOG_LEVEL = user_valves.LOG_LEVEL
        return merged

    def _build_history_input(
        self,
        messages: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        chat_id = metadata.get("chat_id")
        openwebui_model_id = metadata.get("model", {}).get("id")

        def _resolver(item_ids: list[str], resolver_chat: str | None, model_id: str | None) -> dict[str, dict[str, Any]]:
            target_chat = resolver_chat or chat_id or ""
            target_model = model_id or openwebui_model_id
            return self.store.load_items(
                target_chat,
                item_ids,
                model_id=target_model,
            )

        builder = HistoryBuilder(resolve_items=_resolver)
        return builder.build_input_from_messages(
            messages,
            chat_id=chat_id,
            openwebui_model_id=openwebui_model_id,
        )

    @staticmethod
    def _status_unclamp_script() -> dict[str, Any]:
        return {
            "type": "execute",
            "data": {
                "code": """
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
                """,
            },
        }
