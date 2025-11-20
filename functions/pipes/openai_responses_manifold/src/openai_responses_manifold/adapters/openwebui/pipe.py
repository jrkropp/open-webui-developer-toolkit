"""Open WebUI pipe implementation that delegates to the Responses engine."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Any

from open_webui.models.chats import Chats
from open_webui.models.models import ModelForm, Models

from openai_responses_manifold.config.settings import PipeValves, UserValves
from openai_responses_manifold.core.logging import get_logger, logging_context
from openai_responses_manifold.core.model_catalog import supports
from openai_responses_manifold.adapters.openai.client import OpenAIResponsesClient
from openai_responses_manifold.adapters.openai.requests import CompletionCreateParams
from openai_responses_manifold.adapters.openwebui.events import (
    EventCall,
    EventCallerFn,
    EventEmitter,
    EventEmitterFn,
)
from openai_responses_manifold.adapters.openwebui.request_builder import build_responses_body
from openai_responses_manifold.adapters.openwebui.runtime_events import OpenWebUIRuntimeEvents
from openai_responses_manifold.adapters.openwebui.store import ItemStore
from openai_responses_manifold.domain.engine import ResponsesEngine
from openai_responses_manifold.domain.events import RuntimeEvents
from openai_responses_manifold.domain.routing import route_auto_model
from openai_responses_manifold.domain.tools import build_tools


class Pipe:
    class Valves(PipeValves):
        """Admin-level valve configuration."""

    class UserValves(UserValves):
        """Per-user valve overrides."""

    def __init__(self) -> None:
        self.type = "manifold"
        self.id = "openai_responses"
        self.valves = self.Valves()
        self.logger = get_logger(__name__)
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
        __event_emitter__: EventEmitterFn,
        __event_call__: EventCallerFn | None,
        __metadata__: dict[str, Any],
        __tools__: list[dict[str, Any]] | dict[str, Any] | None,
        __task__: dict[str, Any] | None = None,
        __task_body__: dict[str, Any] | None = None,
    ) -> Awaitable[str] | str | None:
        valves = self._merge_valves(
            self.valves, self.UserValves.model_validate(__user__.get("valves", {}))
        )
        openwebui_model_id = __metadata__.get("model", {}).get("id", "")
        user_identifier = __user__.get(valves.PROMPT_CACHE_KEY) or __user__.get("id")
        features = __metadata__.get("features", {}).get("openai_responses", {})

        with logging_context(
            __metadata__.get("session_id"),
            getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO),
            chat_id=__metadata__.get("chat_id"),
            message_id=__metadata__.get("message_id"),
            user_id=__metadata__.get("user_id"),
        ):
            await self._maybe_unclamp_status(__event_call__)
            emitter = EventEmitter(__event_emitter__)
            runtime_events: RuntimeEvents = OpenWebUIRuntimeEvents(emitter)

            completions_body = CompletionCreateParams.model_validate(body)
            responses_body = await build_responses_body(
                completions_body.model_dump(),
                valves=valves,
                metadata=__metadata__,
                user_identifier=user_identifier,
                item_store=self.store,
            )
            provided_tools = __tools__ if __tools__ is not None else body.get("tools")
            extra_tools = getattr(completions_body, "extra_tools", None) or body.get("extra_tools")
            tool_specs = build_tools(
                responses_body,
                valves,
                openwebui_tools=provided_tools if isinstance(provided_tools, dict) else None,
                features=features,
                extra_tools=extra_tools if isinstance(extra_tools, list) else None,
            )
            if tool_specs:
                responses_body.tools = tool_specs
            if (
                isinstance(provided_tools, list)
                and provided_tools
                and not isinstance(provided_tools, dict)
            ):
                await self.engine.emit_notification(
                    runtime_events,
                    content=(
                        "Tool specs were provided without an OpenWebUI tool registry; "
                        "tool calls will be skipped locally."
                    ),
                    level="warning",
                )

            if __task__:
                self.logger.info("Detected task model: %s", __task__)
                task_body = responses_body.model_dump()
                if isinstance(__task_body__, dict):
                    task_body = {**task_body, **__task_body__}
                return await self.engine.run_task_model(task_body, valves)

            try:
                responses_body = await self._apply_model_policies(
                    responses_body,
                    valves,
                    openwebui_model_id,
                    runtime_events,
                )
            except RuntimeError:
                return None

            result = await self.engine.run_streaming_turn(
                responses_body,
                valves=valves,
                metadata=__metadata__,
                events=runtime_events,
                openwebui_tools=provided_tools if isinstance(provided_tools, dict) else None,
            )

            if result.citations and __metadata__.get("chat_id") and __metadata__.get("message_id"):
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    __metadata__["chat_id"],
                    __metadata__["message_id"],
                    {"id": __metadata__["message_id"], "sources": result.citations},
                )

            return result.text

    def _merge_valves(self, pipe_valves: PipeValves, user_valves: UserValves) -> PipeValves:
        merged = pipe_valves.model_copy(deep=True)
        if user_valves.LOG_LEVEL != "INHERIT":
            merged.LOG_LEVEL = user_valves.LOG_LEVEL
        return merged

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

    async def _maybe_unclamp_status(self, event_call: EventCallerFn | None) -> None:
        if not event_call:
            return
        # Temporary UI hack to unclamp status text so reasoning tokens can be shown multi-line.
        call = EventCall(event_call)
        await call.execute(self._status_unclamp_script())

    async def _apply_model_policies(
        self,
        responses_body: Any,
        valves: PipeValves,
        openwebui_model_id: str,
        events: RuntimeEvents,
    ) -> Any:
        responses_body = await self._ensure_native_function_calling_if_needed(
            responses_body, openwebui_model_id, events
        )
        responses_body = await self._ensure_routed_auto_model(
            responses_body, valves, openwebui_model_id, events
        )
        self._apply_reasoning_options(responses_body, valves)
        self._apply_parallel_tool_policy(responses_body, valves)
        return responses_body

    async def _ensure_native_function_calling_if_needed(
        self,
        responses_body: Any,
        openwebui_model_id: str,
        events: RuntimeEvents,
    ) -> Any:
        tools = responses_body.tools or []
        if not (tools and supports("function_calling", responses_body.model)):
            return responses_body
        model = Models.get_model_by_id(openwebui_model_id)
        if not model:
            return responses_body
        params = dict(model.params or {})
        if params.get("function_calling") == "native":
            return responses_body

        await self.engine.emit_notification(
            events,
            content=(
                f"Enabling native function calling for model: {openwebui_model_id}. "
                "Please re-run your query."
            ),
            level="info",
        )
        params["function_calling"] = "native"
        form_data = model.model_dump()
        form_data["params"] = params
        Models.update_model_by_id(openwebui_model_id, ModelForm(**form_data))
        await self.engine.emit_error(
            events,
            "Function calling enabled; please re-run your query.",
            done=True,
        )
        raise RuntimeError("Function calling not yet enabled; user must retry")

    async def _ensure_routed_auto_model(
        self,
        responses_body: Any,
        valves: PipeValves,
        openwebui_model_id: str,
        events: RuntimeEvents,
    ):
        if openwebui_model_id.endswith(".gpt-5-auto-dev"):
            return await route_auto_model(
                self.engine.client,
                router_model="gpt-4.1-mini",
                responses_body=responses_body,
                valves=valves,
                tools=responses_body.tools or [],
                events=events,
            )

        if openwebui_model_id.endswith(".gpt-5-auto"):
            responses_body.model = "gpt-5-chat-latest"
            await self.engine.emit_notification(
                events,
                content="Model router coming soon — using gpt-5-chat-latest (GPT-5 Fast).",
                level="warning",
            )
        return responses_body

    def _apply_reasoning_options(self, responses_body: Any, valves: PipeValves) -> None:
        if supports("reasoning_summary", responses_body.model) and valves.REASONING_SUMMARY != "disabled":
            existing_reasoning = (
                responses_body.reasoning if isinstance(responses_body.reasoning, dict) else {}
            )
            responses_body.reasoning = {**existing_reasoning, "summary": valves.REASONING_SUMMARY}

        if (
            supports("reasoning", responses_body.model)
            and valves.PERSIST_REASONING_TOKENS != "disabled"
            and responses_body.store is False
        ):
            responses_body.include = responses_body.include or []
            if "reasoning.encrypted_content" not in responses_body.include:
                responses_body.include.append("reasoning.encrypted_content")

    def _apply_parallel_tool_policy(self, responses_body: Any, valves: PipeValves) -> None:
        has_web_search = any(
            isinstance(tool, dict) and tool.get("type") == "web_search"
            for tool in (responses_body.tools or [])
        )
        if has_web_search:
            responses_body.parallel_tool_calls = False
            if getattr(valves, "WEB_SEARCH_INCLUDE_SOURCES", True):
                responses_body.include = responses_body.include or []
                if "web_search_call.action.sources" not in responses_body.include:
                    responses_body.include.append("web_search_call.action.sources")
            return
        responses_body.parallel_tool_calls = getattr(valves, "PARALLEL_TOOL_CALLS", True)
