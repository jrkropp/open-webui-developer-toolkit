"""Open WebUI pipe implementation that delegates to a Responses engine."""

from __future__ import annotations

import asyncio
import datetime
import inspect
import json
import logging
import random
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable
from time import perf_counter
from typing import Any

from fastapi import Request
from open_webui.models.chats import Chats
from open_webui.models.models import ModelForm, Models

from .core import (
    CompletionsBody,
    ResponsesBody,
    SessionLogger,
    merge_usage_stats,
    supports,
    wrap_code_block,
    wrap_event_emitter,
)
from .engine import EventEmitter, ResponsesEngine
from .features import build_tools, route_gpt5_auto
from .settings import PipeUserValves, PipeValves


class Pipe:
    class Valves(PipeValves):
        """Admin-level valve configuration."""

    class UserValves(PipeUserValves):
        """Per-user valve overrides."""

    def __init__(self) -> None:
        self.type = "manifold"
        self.id = "openai_responses"
        self.valves = self.Valves()
        self.logger = SessionLogger.get_logger(__name__)
        self.engine = ResponsesEngine(logger=self.logger)

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
    ) -> AsyncGenerator[str, None] | str | None:
        valves = self._merge_valves(
            self.valves, self.UserValves.model_validate(__user__.get("valves", {}))
        )
        openwebui_model_id = __metadata__.get("model", {}).get("id", "")
        user_identifier = __user__[valves.PROMPT_CACHE_KEY]
        features = __metadata__.get("features", {}).get("openai_responses", {})

        SessionLogger.session_id.set(__metadata__.get("session_id"))
        SessionLogger.log_level.set(getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO))

        if __event_call__:
            await __event_call__(
                {
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
            )

        completions_body = CompletionsBody.model_validate(body)
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
            openwebui_model_id=openwebui_model_id or None,
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
            __tools__=tool_registry,
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
            responses_body = await route_gpt5_auto(
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
            if supports("web_search_tool", responses_body.model):
                responses_body.include = list(responses_body.include or [])
                if "web_search_call.action.sources" not in responses_body.include:
                    responses_body.include.append("web_search_call.action.sources")

        input_items = responses_body.input if isinstance(responses_body.input, list) else None
        if input_items:
            last_item = input_items[-1]
            content_blocks = last_item.get("content") if last_item.get("role") == "user" else None
            first_block = (
                content_blocks[0] if isinstance(content_blocks, list) and content_blocks else {}
            )
            last_user_text = (first_block.get("text") or "").strip().lower()

            directive_to_verbosity = {"add details": "high", "more concise": "low"}
            verbosity_value = directive_to_verbosity.get(last_user_text)

            if verbosity_value and supports("verbosity", responses_body.model):
                current_text_params = dict(getattr(responses_body, "text", {}) or {})
                current_text_params["verbosity"] = verbosity_value
                responses_body.text = current_text_params
                input_items.pop()
                await self.engine.emit_notification(
                    __event_emitter__,
                    f"Regenerating with verbosity set to {verbosity_value}.",
                    level="info",
                )
                self.logger.debug(
                    "Set text.verbosity=%s based on regenerate directive '%s'",
                    verbosity_value,
                    last_user_text,
                )

        self.logger.debug(
            "Transformed ResponsesBody: %s",
            json.dumps(responses_body.model_dump(exclude_none=True), indent=2, ensure_ascii=False),
        )

        if responses_body.stream:
            return await self.engine.stream(
                responses_body, valves, __event_emitter__, __metadata__, tool_registry or {}
            )

        await self.engine.emit_error(
            __event_emitter__,
            "Non-streaming is currently not supported with the OpenAI Responses Manifold.  Please enable streaming and try again",
            show_error_message=True,
        )
        return ""

    def _merge_valves(
        self, global_valves: Pipe.Valves, user_valves: Pipe.UserValves
    ) -> Pipe.Valves:
        if not user_valves:
            return global_valves
        update = {
            key: value
            for key, value in user_valves.model_dump().items()
            if value is not None and str(value).lower() != "inherit"
        }
        return global_valves.model_copy(update=update)
