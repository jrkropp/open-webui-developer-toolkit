"""Open WebUI pipe implementation that delegates to the Responses engine."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Any

from open_webui.models.models import ModelForm, Models

from openai_responses_manifold.config.settings import PipeValves, UserValves
from openai_responses_manifold.domain.model_catalog import supports
from openai_responses_manifold.domain.openai_requests import CompletionCreateParams
from openai_responses_manifold.application.engine import ResponsesEngine
from openai_responses_manifold.application.request_builder import build_responses_body
from openai_responses_manifold.application.routing import route_auto_model
from openai_responses_manifold.application.tools import build_tools
from openai_responses_manifold.infrastructure.logging import get_logger, logging_context
from openai_responses_manifold.infrastructure.openai_client import OpenAIResponsesClient
from openai_responses_manifold.infrastructure.openwebui_events import (
    EventCall,
    EventCallerFn,
    EventEmitterFn,
)
from openai_responses_manifold.infrastructure.openwebui_store import ItemStore


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
        user_identifier = __user__[valves.PROMPT_CACHE_KEY]
        features = __metadata__.get("features", {}).get("openai_responses", {})

        with logging_context(
            __metadata__.get("session_id"),
            getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO),
            chat_id=__metadata__.get("chat_id"),
            message_id=__metadata__.get("message_id"),
            user_id=__metadata__.get("user_id"),
        ):
            await self._maybe_unclamp_status(__event_call__)

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

            if __task__:
                self.logger.info("Detected task model: %s", __task__)
                return await self.engine.run_task_model(responses_body.model_dump(), valves)

            responses_body = await self._ensure_native_function_calling_if_needed(
                responses_body, openwebui_model_id, __event_emitter__
            )
            responses_body = await self._ensure_routed_auto_model(
                responses_body, valves, openwebui_model_id, __event_emitter__
            )
            self._apply_reasoning_options(responses_body, valves)
            self._apply_parallel_tool_policy(responses_body, valves)

            return await self.engine.run_streaming_turn(
                responses_body,
                valves=valves,
                metadata=__metadata__,
                event_emitter=__event_emitter__,
                openwebui_tools=provided_tools if isinstance(provided_tools, dict) else None,
            )

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
        event_emitter: EventEmitterFn,
    ):
        await self._ensure_native_function_calling_if_needed(
            responses_body, openwebui_model_id, event_emitter
        )
        responses_body = await self._ensure_routed_auto_model(
            responses_body, valves, openwebui_model_id, event_emitter
        )
        self._apply_reasoning_options(responses_body, valves)
        self._apply_parallel_tool_policy(responses_body, valves)
        return responses_body

    async def _ensure_native_function_calling_if_needed(
        self,
        responses_body: Any,
        openwebui_model_id: str,
        event_emitter: EventEmitterFn,
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
            event_emitter,
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
        return responses_body

    async def _ensure_routed_auto_model(
        self,
        responses_body: Any,
        valves: PipeValves,
        openwebui_model_id: str,
        event_emitter: EventEmitterFn,
    ):
        if openwebui_model_id.endswith(".gpt-5-auto-dev"):
            return await route_auto_model(
                self.engine.client,
                router_model="gpt-4.1-mini",
                responses_body=responses_body,
                valves=valves,
                tools=responses_body.tools or [],
                event_emitter=event_emitter,
            )

        if openwebui_model_id.endswith(".gpt-5-auto"):
            responses_body.model = "gpt-5-chat-latest"
            await self.engine.emit_notification(
                event_emitter,
                content="Model router coming soon — using gpt-5-chat-latest (GPT-5 Fast).",
                level="warning",
            )
        return responses_body

    def _apply_reasoning_options(self, responses_body: Any, valves: PipeValves) -> None:
        if supports("reasoning_summary", responses_body.model) and valves.REASONING_SUMMARY != "disabled":
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

    def _apply_parallel_tool_policy(self, responses_body: Any, valves: PipeValves) -> None:
        if any(
            isinstance(tool, dict) and tool.get("type") == "web_search"
            for tool in (responses_body.tools or [])
        ):
            responses_body.parallel_tool_calls = False
            return
        responses_body.parallel_tool_calls = getattr(valves, "PARALLEL_TOOL_CALLS", True)
