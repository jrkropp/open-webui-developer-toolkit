"""
title: OpenAI Responses API Manifold
id: openai_responses
author: Justin Kropp
author_url: https://github.com/jrkropp
funding_url: https://github.com/jrkropp/open-webui-developer-toolkit
description: Brings OpenAI Response API support to Open WebUI, enabling features not possible via Completions API.
version: 0.9.2
license: MIT
requirements: orjson
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Standard lib & third-party imports
# ─────────────────────────────────────────────────────────────────────────────
import asyncio
import datetime
import inspect
from io import StringIO
import json
import logging
import os
import random
import re
import sys
import time
from collections import defaultdict
from contextvars import ContextVar

# Third-party imports
import aiohttp
import orjson
from fastapi import Request
from pydantic import BaseModel, Field

# Typing imports
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
)

# ─────────────────────────────────────────────────────────────────────────────
# Open WebUI internals
# ─────────────────────────────────────────────────────────────────────────────
from open_webui.models.chats import Chats, ChatModel
from open_webui.models.models import Model
from open_webui.internal.db import get_db

from open_webui.utils.misc import get_message_list

# ─────────────────────────────────────────────────────────────────────────────

FEATURE_SUPPORT = {
    "web_search_tool": {"gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"}, # OpenAI's built-in web search tool.
    "image_gen_tool": {"gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-nano", "o3"}, # OpenAI's built-in image generation tool.
    "function_calling": {"gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "gpt-4.1-nano", "o3", "o4-mini", "o3-mini"}, # OpenAI's native function calling support.
    "reasoning": {"o3", "o4-mini", "o3-mini"}, # OpenAI's reasoning models.
    "reasoning_summary": {"o3", "o4-mini", "o4-mini-high", "o3-mini", "o3-mini-high" }, # OpenAI's reasoning summary feature.  May require OpenAI org verification before use.
}

current_session_id = ContextVar("current_session_id", default=None)
current_log_level = ContextVar("current_log_level", default=logging.INFO)
logs_by_msg_id = defaultdict(list)


class SessionIDFilter(logging.Filter):
    """Attach the current session ID to each log record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.session_id = getattr(record, "session_id", None) or current_session_id.get()
        return True


class ContextLevelFilter(logging.Filter):
    """Filter records using the per-session log level from :data:`current_log_level`."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        return record.levelno >= current_log_level.get()

# Precompiled regex for stripping <details> blocks from assistant text
DETAILS_RE = re.compile(r"<details\b[^>]*>.*?<\/details>", flags=re.IGNORECASE | re.DOTALL)

class Pipe:
    class Valves(BaseModel):
        BASE_URL: str = Field(
            default=((os.getenv("OPENAI_API_BASE_URL") or "").strip() or "https://api.openai.com/v1"),
            description="The base URL to use with the OpenAI SDK. Defaults to the official OpenAI API endpoint. Supports LiteLLM and other custom endpoints.",
        )
        API_KEY: str = Field(
            default=(os.getenv("OPENAI_API_KEY") or "").strip() or "sk-xxxxx",
            description="Your OpenAI API key. Defaults to the value of the OPENAI_API_KEY environment variable.",
        )
        MODEL_ID: str = Field(
            default="gpt-4.1, gpt-4o",
            description="Comma separated OpenAI model IDs. Each ID becomes a model entry in WebUI. Supports the pseudo models 'o3-mini-high' and 'o4-mini-high', which map to 'o3-mini' and 'o4-mini' with reasoning effort forced to high.",
        )
        ENABLE_REASONING_SUMMARY: Literal["auto", "concise", "detailed", None] = Field(
            default=None,
            description="Reasoning summary style for o-series models (supported by: o3, o4-mini). Ignored for others. Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-reasoning",
        )
        ENABLE_WEB_SEARCH: bool = Field(
            default=False,
            description="Enable OpenAI's built-in 'web_search' tool when supported (gpt-4.1, gpt-4.1-mini, gpt-4o, gpt-4o-mini).  Note this adds the tool to each call which may slow down responses. Read more: https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses",
        )
        SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None] = Field(
            default="medium",
            description="Specifies the OpenAI web search context size: low | medium | high. Default is 'medium'. Affects cost, quality, and latency. Only used if ENABLE_WEB_SEARCH=True.",
        )
        PARALLEL_TOOL_CALLS: bool = Field(
            default=True,
            description="Whether tool calls can be parallelized. Defaults to True if not set. Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-parallel_tool_calls",
        )
        MAX_TOOL_CALL_LOOPS: int = Field(
            default=5,
            description="Maximum number of tool calls the model can make in a single request. This is a hard stop safety limit to prevent infinite loops. Defaults to 5.",
        )
        PERSIST_TOOL_RESULTS: bool = Field(
            default=True,
            description="Persist tool call results across conversation turns. When disabled, tool results are not stored in the chat history.",
        )
        STORE_RESPONSE: bool = Field(
            default=False,
            description="Whether to store the generated model response (on OpenAI's side) for later debugging. Defaults to False.",
        )
        LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
            default=os.getenv("GLOBAL_LOG_LEVEL", "INFO").upper(),
            description="Select logging level.  Recommend INFO or WARNING for production use. DEBUG is useful for development and debugging.",
        )

    class UserValves(BaseModel):
        """Per-user valve overrides."""
        LOG_LEVEL: Literal[
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "INHERIT"
        ] = Field(
            default="INHERIT",
            description="Select logging level. 'INHERIT' uses the pipe default.",
        )

    class SelfTerminate(Exception):
        """Intentionally raised to terminate task early without triggering CancelledError logic."""
        pass

    def __init__(self):
        self.type = "manifold"
        self.valves = self.Valves()  # Note: valve values are not accessible in __init__. Access from pipes() or pipe() methods.
        
        self.session: aiohttp.ClientSession | None = None
        
        self.log = logging.getLogger(__name__)
        if not self.log.handlers:  # Prevent duplicate logs
            self.log.propagate = False
            self.log.setLevel(logging.DEBUG)
            self.log.addFilter(SessionIDFilter())
            self.log.addFilter(ContextLevelFilter())

            console = logging.StreamHandler(sys.stdout)
            console.setFormatter(logging.Formatter("%(levelname)s [mid=%(session_id)s] %(message)s"))
            self.log.addHandler(console)

            mem_handler = logging.Handler()
            mem_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            mem_handler.emit = lambda r: logs_by_msg_id.setdefault(getattr(r, "session_id", None), []).append(mem_handler.format(r)) if getattr(r, "session_id", None) else None
            self.log.addHandler(mem_handler)
    
    def pipes(self):

        try :
            models = [m.strip() for m in self.valves.MODEL_ID.split(",") if m.strip()]

            # Then return the model info for Open WebUI
            return [
                {"id": model_id, "name": f"OpenAI: {model_id}", "direct": True}
                for model_id in models
            ]
        finally:
            # TODO Try setting native function calling parm here.
            pass

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Request,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]],
        __metadata__: dict[str, Any],
        __tools__: list[dict[str, Any]] | dict[str, Any] | None,
        __task__: Optional[dict[str, Any]] = None,
        __task_body__: Optional[dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None] | str | None:
        """
        Single entry point:
        1) If body["stream"] is True, return an async generator
        2) Otherwise, await _multi_turn_non_streaming(...) for a final string.
        """
        # Get or create aiohttp session (aiohttp is used for performance).
        self.session = await self._get_or_create_aiohttp_session()

        chat_id = __metadata__.get("chat_id", None)
        message_id = __metadata__.get("message_id", None)
        valves = self._merge_valves(self.valves, self.UserValves.model_validate(__user__.get("valves", {})))
        current_session_id.set(__metadata__.get("session_id", None))
        current_log_level.set(getattr(logging, valves.LOG_LEVEL.upper(), logging.INFO))

        # Extract Model ID from body["model"]
        model_id = str(body.get("model")).strip()  # e.g., openai_responses.o4-mini-high
        model_id = model_id.split(".", 1)[-1]  # e.g., o4-mini-high
        if model_id in {"o3-mini-high", "o4-mini-high"}: # OpenAI pseudo models
            model_id = model_id.replace("-high", "")
            body["reasoning_effort"] = "high"

        # Detect if task model (generate title, generate tags, etc.), handle it separately
        if __task__:
            self.log.debug("Detected task model: %s", __task__)
            self.log.debug("Task body: %s", __task_body__)

            return await self._handle_task(body, __user__, __request__, __event_emitter__, __metadata__, __tools__) # Placeholder for task handling logic

        try:
            # Build the OpenAI Responses API request body
            transformed_body = {
                "model": model_id,
                "instructions": next((msg["content"] for msg in reversed(body.get("messages", [])) if msg.get("role") == "system"), ""),
                "input": build_responses_history_by_chat_id_and_message_id(chat_id, message_id, model_id=model_id),
                "stream": body.get("stream", False),
                "user": __user__.get("email", "unknown_user"),
                "store": valves.STORE_RESPONSE,
                **({"temperature": body["temperature"]} if "temperature" in body else {}),
                **({"top_p": body["top_p"]} if "top_p" in body else {}),
                **({"max_tokens": body["max_tokens"]} if "max_tokens" in body else {}),
                **({"parallel_tool_calls": valves.PARALLEL_TOOL_CALLS} if valves.PARALLEL_TOOL_CALLS else {}),
                # Conditionally add tools only if function calling is supported and enabled
                **(
                    {
                        "tools": [
                            *self.transform_tools_for_responses_api(__tools__),

                            # Conditionally include web_search
                            *(
                                [self.web_search_tool(valves)]
                                if (model_id in FEATURE_SUPPORT["web_search_tool"] and (valves.ENABLE_WEB_SEARCH ))
                                else []
                            )
                        ]
                    }
                    if model_id in FEATURE_SUPPORT["function_calling"]
                    else {}
                ),
                # Conditionally add reasoning dict if the model supports reasoning AND (effort or summary) was specified
                **(
                    {
                        "reasoning": {
                            **({"effort": body["reasoning_effort"]} if "reasoning_effort" in body else {}),
                            **(
                                {"summary": valves.ENABLE_REASONING_SUMMARY}
                                if (
                                    valves.ENABLE_REASONING_SUMMARY
                                    and model_id in FEATURE_SUPPORT["reasoning_summary"]
                                )
                                else {}
                            ),
                        }
                    }
                    if (model_id in FEATURE_SUPPORT["reasoning"]) else {}
                ),
                # Only include "include" if it's a reasoning model. Included encrypted reasoning tokens (important for multi-turn loops).
                **(
                    {
                        "include": ["reasoning.encrypted_content"]
                    }
                    if model_id in FEATURE_SUPPORT["reasoning"]
                    else {}
                ),
            }

            # Send to OpenAI Responses API
            is_streaming = body.get("stream", False)
            if is_streaming:
                # Return async generator for partial text
                return self._multi_turn_streaming(body, transformed_body, valves, __event_emitter__, __metadata__, __tools__)
            else:
                # Return final text (non-streaming)
                return await self._multi_turn_non_streaming(body, transformed_body, valves, __event_emitter__, __metadata__, __tools__)

        except Exception as caught_exception:
            await self._emit_error(__event_emitter__, caught_exception, show_error_message=True, show_error_log_citation=True, done=True)

    # -------------------------------------------------------------------------
    # Helper: Handle simple task models
    # -------------------------------------------------------------------------
    async def _handle_task(
        self,
        body: Dict[str, Any],
        __user__: Dict[str, Any],
        __request__: Request,
        __event_emitter__: Callable[[Dict[str, Any]], Awaitable[None]],
        __metadata__: Dict[str, Any],
        __tools__: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call the Responses API for task requests and return OpenAI-style output."""

        valves = self._merge_valves(self.valves, self.UserValves.model_validate(__user__.get("valves", {})))
        model_id = str(body.get("model", "")).split(".", 1)[-1].strip()
        transformed_body = {
            "model": model_id,
            "instructions": "",
            "input": body.get("messages"),
            "stream": False,
        }

        response = await self._call_llm_non_stream(
            transformed_body,
            api_key=valves.API_KEY,
            base_url=valves.BASE_URL,
        )

        text_parts: list[str] = []
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text_parts.append(content.get("text", ""))

        message = "".join(text_parts)

        return message
                
    # -------------------------------------------------------------------------
    # 1) Multi-turn loop: STREAMING
    # -------------------------------------------------------------------------
    async def _multi_turn_streaming(
        self,
        body: Dict[str, Any],                                       # The unmodified body from Open WebUI (completions API)
        transformed_body: Dict[str, Any],                           # The transformed body for OpenAI Responses API
        valves: Pipe.Valves,                                        # Contains config: MAX_TOOL_CALL_LOOPS, API_KEY, etc.
        event_emitter: Callable[[Dict[str, Any]], Awaitable[None]], # Function to emit events to the front-end UI
        metadata: Dict[str, Any] = {},                              # Metadata for the request (e.g., session_id, chat_id)
        tools: Optional[Dict[str, Dict[str, Any]]] = None,          # Optional tools dictionary for function calls
    ) -> AsyncGenerator[str, None]:
        """
        Streaming multi-turn conversation loop using OpenAI Responses API.

        Workflow:
        - The conversation loop runs up to `valves.MAX_TOOL_CALL_LOOPS` times to prevent infinite tool-calling cycles.
        1) In each iteration, `_stream_sse_events(...)` is called to yield partial LLM outputs as SSE events.
        2) For each event:
            - Partial text deltas (`response.output_text.delta`) are yielded to the UI for real-time updates.
            - Other event types, such as reasoning summaries and tool start/end notifications, are handled and emitted as needed.
        3) When a 'response.completed' event is received, the final output is parsed to check for any function (tool) calls.
            - If a function call is present, it is executed, its result is appended to `transformed_body["input"]`, and the loop continues for another turn.
            - If no function call is present, the conversation is considered complete and the loop exits.
        """

        reasoning_map: Dict[int, str] = {}
        total_usage: Dict[str, Any] = {}
        collected_items: List[dict] = []  # For storing function_call, function_call_output, etc.

        started_msgs = {
            "web_search_call": [
                "🔍 Hmm, let me quickly check online…",
                "🔍 One sec—looking that up…",
                "🔍 Just a moment, searching the web…",
            ],
            "function_call": [
                "🛠️ Running the {fn} tool…",
                "🛠️ Let me try {fn}…",
                "🛠️ Calling {fn} real quick…",
            ],
            "file_search_call": [
                "📂 Let me skim those files…",
                "📂 One sec, scanning the documents…",
                "📂 Checking the files right now…",
            ],
            "image_generation_call": [
                "🎨 Let me create that image…",
                "🎨 Give me a moment to sketch…",
                "🎨 Working on your picture…",
            ],
            "local_shell_call": [
                "💻 Let me run that command…",
                "💻 Hold on, executing locally…",
                "💻 Firing up that shell command…",
            ],
        }

        finished_msgs = {
            "web_search_call": [
                "🔎 Got it—here's what I found!",
                "🔎 All set—found that info!",
                "🔎 Okay, done searching!",
            ],
            "function_call": [
                "🛠️ Done—the tool finished!",
                "🛠️ Got the results for you!",
            ],
            "file_search_call": [
                "📂 Done checking files!",
                "📂 Found what I needed!",
                "📂 Got the documents ready!",
            ],
            "image_generation_call": [
                "🎨 Your image is ready!",
                "🎨 Picture's finished!",
                "🎨 All done—image created!",
            ],
            "local_shell_call": [
                "💻 Command complete!",
                "💻 Finished running that!",
                "💻 Shell task done!",
            ],
        }

        tools = tools or {}
        final_output = StringIO()

        self.log.debug(
            "Entering _multi_turn_streaming with up to %d loops",
            valves.MAX_TOOL_CALL_LOOPS,
        )

        try:
            for loop_idx in range(valves.MAX_TOOL_CALL_LOOPS):
                final_response_data: dict[str, Any] | None = None
                reasoning_map.clear()
                self.log.debug(
                    "Starting loop %d of %d", loop_idx + 1, valves.MAX_TOOL_CALL_LOOPS
                )
                async for event in self._call_llm_sse(transformed_body,api_key=valves.API_KEY,base_url=valves.BASE_URL):
                    event_type = event.get("type")

                    # Partial text output
                    if event_type == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            #yield delta  # Yield partial text to Open WebUI
                            final_output.write(delta)  # Accumulate in final_output
                            yield delta

                        continue # continue to next event

                    # Partial reasoning summary output
                    elif event_type == "response.reasoning_summary_text.delta":
                        idx = event.get("summary_index", 0)
                        delta = event.get("delta", "")
                        if delta:
                            # 1) Accumulate for this summary_index
                            reasoning_map[idx] = reasoning_map.get(idx, "") + delta

                            # 2) Merge all blocks (sorted), separated by ---
                            all_text = "\n\n --- \n\n".join(reasoning_map[i] for i in sorted(reasoning_map))

                            # 3) Extract latest title, else fallback to 'Thinking...'
                            matches = re.findall(r"\*\*(.+?)\*\*", all_text, flags=re.DOTALL)
                            latest_title = matches[-1].strip() if matches else "Thinking..."

                            # 4) Build a minimal snippet (omit type="reasoning")
                            snippet = (
                                f"<details type=\"{__name__}.reasoning\" done=\"false\">\n"
                                f"<summary>🧠{latest_title}</summary>\n"
                                f"{all_text}\n"
                                "</details>"
                            )
                            if event_emitter:
                                await event_emitter(
                                    {"type": "chat:completion", "data": {"content": snippet}}
                                )

                            # 5) Emit to the front end
                            yield "" # Yield an empty string to release the event loop for responsiveness

                        continue

                    # Output item added (e.g., tool call started, reasoning started, etc..)
                    elif event_type == "response.output_item.added":
                        item = event.get("item", {})
                        item_type = item.get("type", "")

                        self.log.debug("output_item.added event received: %s", json.dumps(item, indent=2, ensure_ascii=False))

                        if item_type in started_msgs:
                            template = random.choice(started_msgs[item_type])
                            msg = template.format(fn=item.get("name", "a tool"))
                            await self._emit_status(event_emitter, msg, done=False, hidden=False)
                        
                        continue  # continue to next event

                    # Output item done (e.g., tool call finished, reasoning done, etc.)
                    elif event_type == "response.output_item.done":
                        item = event.get("item", {})
                        item_type = item.get("type", "")

                        if item_type in finished_msgs:
                            template = random.choice(finished_msgs[item_type])
                            msg = template.format(fn=item.get("name", "Tool"))
                            await self._emit_status(event_emitter, msg, done=True, hidden=False)

                        if item_type == "reasoning":
                            # Merge all partial reasoning so far
                            all_text = "\n\n --- \n\n".join(reasoning_map[i] for i in sorted(reasoning_map))

                            if all_text:
                                all_text += "\n\n --- \n\n"

                                final_snippet = (
                                    f'<details type=\"{__name__}.reasoning\" done="true">\n'
                                    f"<summary>Done thinking!</summary>\n"
                                    f"{all_text}\n"
                                    "</details>"
                                )
                                yield final_snippet  # Yield an empty string to release the event loop for responsiveness
                            else:
                                await self._emit_status(event_emitter, "Done thinking!", done=True, hidden=False)

                            reasoning_map.clear()

                        continue  # continue to next event

                    # Response completed event
                    elif event_type == "response.completed":
                        self.log.debug("Response completed event received.")
                        final_response_data = event.get("response", {})
                        yield ""
                        break # Exit the streaming loop to process the final response
                
                # Capture the final output items
                collected_items.extend(final_response_data.get("output", []))
                usage = final_response_data.get("usage", {})
                if usage:
                    usage["turn_count"] = 1
                    usage["function_call_count"] = sum(
                        1 for i in final_response_data["output"] if i["type"] == "function_call"
                    )
                    update_usage_totals(total_usage, usage)

                transformed_body["input"].extend(final_response_data.get("output", []))

                # Run function calls if present
                calls = [i for i in final_response_data.get("output", []) if i["type"] == "function_call"]
                if calls:
                    function_call_outputs = await self._execute_function_calls(calls, tools)
                    collected_items.extend(function_call_outputs) # Store function call outputs to be persisted in DB later
                    transformed_body["input"].extend(function_call_outputs) # Append to input for next iteration
                else:
                    self.log.debug("No pending function calls. Exiting loop.")
                    break # LLM response is complete, no further tool calls

        except Exception as e:
            await self._emit_error(
                event_emitter,
                e,
                show_error_message=True,
                show_error_log_citation=True,
                done=True,
            )
            return
        

        finally:
            self.log.debug("Exiting _multi_turn_streaming loop.")
            # Final cleanup: close the aiohttp session if it was created

            if total_usage:
                # Emit final usage stats if available
                await self._emit_completion(event_emitter, usage=total_usage, done=True)       

            # If valves is DEBUG or user_valves is as value other than "INHERIT", emit citation with logs
            # TODO ADD LOGIC TO DETECT USER VALVES /= "INHERIT"
            if valves.LOG_LEVEL == "DEBUG":
                if event_emitter:
                    logs = logs_by_msg_id.get(current_session_id.get(), [])
                    if logs:
                        await self._emit_citation(
                            event_emitter,
                            "\n".join(logs),
                            valves.LOG_LEVEL.capitalize() + " Logs",
                        )

    # -------------------------------------------------------------------------
    # 2) Multi-turn loop: NON-STREAMING
    # -------------------------------------------------------------------------
    async def _multi_turn_non_streaming(
        self,
        body: Dict[str, Any],                                       # The unmodified body from Open WebUI (completions API)
        transformed_body: Dict[str, Any],                           # The transformed body for OpenAI Responses API
        valves: Pipe.Valves,                                        # Contains config: MAX_TOOL_CALL_LOOPS, API_KEY, etc.
        event_emitter: Callable[[Dict[str, Any]], Awaitable[None]], # Function to emit events to the front-end UI
        metadata: Dict[str, Any] = {},                              # Metadata for the request (e.g., session_id, chat_id)
        tools: Optional[Dict[str, Dict[str, Any]]] = None,          # Optional tools dictionary for function calls
    ) -> str:
        """
        Multi-turn conversation loop without streaming chunks.

        This mirrors :meth:`_multi_turn_streaming` but issues a full
        HTTP request each turn and processes the returned JSON before
        optionally calling tools again.
        """

        tools = tools or {}
        final_output = StringIO()
        total_usage: Dict[str, Any] = {}
        collected_items: List[dict] = []

        try:
            for loop_idx in range(valves.MAX_TOOL_CALL_LOOPS):
                response = await self._call_llm_non_stream(
                    transformed_body,
                    api_key=valves.API_KEY,
                    base_url=valves.BASE_URL,
                )

                items = response.get("output", [])
                collected_items.extend(items)

                # append text from any message blocks
                for item in items:
                    if item.get("type") != "message":
                        continue
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            final_output.write(content.get("text", ""))

                usage = response.get("usage", {})
                if usage:
                    usage["turn_count"] = 1
                    usage["function_call_count"] = sum(
                        1 for i in items if i.get("type") == "function_call"
                    )
                    update_usage_totals(total_usage, usage)

                transformed_body["input"].extend(items)

                # Run tools if requested
                calls = [i for i in items if i.get("type") == "function_call"]
                if calls:
                    fn_outputs = await self._execute_function_calls(calls, tools)
                    collected_items.extend(fn_outputs)
                    transformed_body["input"].extend(fn_outputs)
                else:
                    break

        except Exception as e:  # pragma: no cover - network errors
            await self._emit_error(
                event_emitter,
                e,
                show_error_message=True,
                show_error_log_citation=True,
                done=True,
            )
            return ""
        finally:
            if total_usage:
                await self._emit_completion(event_emitter, usage=total_usage, done=True)

        return final_output.getvalue()

    # -------------------------------------------------------------------------
    # HELPER: SSE LLM Call
    # -------------------------------------------------------------------------
    async def _call_llm_sse(
        self,
        request_params: dict[str, Any],
        api_key: str,
        base_url: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streams SSE events from OpenAI's /responses endpoint and yields them ASAP.
        Optimized for low latency.
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        url = base_url.rstrip("/") + "/responses"

        buf = bytearray()
        orjson_loads = orjson.loads  # Cached reference for speed
        async with self.session.post(url, json=request_params, headers=headers) as resp:
            resp.raise_for_status()

            async for chunk in resp.content.iter_chunked(4096):
                buf.extend(chunk)
                start_idx = 0
                # Process all complete lines in the buffer
                while True:
                    newline_idx = buf.find(b"\n", start_idx)
                    if newline_idx == -1:
                        break
                    
                    line = buf[start_idx:newline_idx].strip()
                    start_idx = newline_idx + 1

                    # Skip empty lines, comment lines, or anything not starting with "data:"
                    if (not line or line.startswith(b":") or not line.startswith(b"data:")):
                        continue

                    data_part = line[5:].strip()
                    if data_part == b"[DONE]":
                        return  # End of SSE stream
                    
                    # Yield JSON-decoded data
                    yield orjson_loads(data_part)

                # Remove processed data from the buffer
                if start_idx > 0:
                    del buf[:start_idx]

    # -------------------------------------------------------------------------
    # HELPER: Non-stream LLM Call
    # -------------------------------------------------------------------------
    async def _call_llm_non_stream(
        self,
        request_params: dict[str, Any],
        api_key: str,
        base_url: str,
    ) -> Dict[str, Any]:
        """Perform a non-streaming POST request to the Responses API."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = base_url.rstrip("/") + "/responses"

        async with self.session.post(url, json=request_params, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()

    # -------------------------------------------------------------------------
    # HELPER: Execute Tool Call
    # -------------------------------------------------------------------------
    @staticmethod
    async def _execute_function_calls(
        calls: list[dict],                      # raw call-items from the LLM
        tools: dict[str, dict[str, Any]],       # name → {callable, …}
    ) -> list[dict]:
        """
        Run every function-call in *parallel* and return the synthetic
        `function_call_output` items the LLM expects next turn.
        """
        def _make_task(call):
            tool_cfg = tools.get(call["name"])
            if not tool_cfg:                                 # tool missing
                return asyncio.sleep(0, result="Tool not found")

            fn = tool_cfg["callable"]
            args = orjson.loads(call["arguments"])

            if inspect.iscoroutinefunction(fn):              # async tool
                return fn(**args)
            else:                                            # sync tool
                return asyncio.to_thread(fn, **args)

        tasks   = [_make_task(call) for call in calls]       # ← fire & forget
        results = await asyncio.gather(*tasks)               # ← runs in parallel

        return [
            {
                "type":   "function_call_output",
                "call_id": call["call_id"],
                "output":  str(result),
            }
            for call, result in zip(calls, results)
        ]


    # ------------------------------------------------------
    # helper: Merge User Valve Overrides
    # ------------------------------------------------------
    def _merge_valves(self, global_valves, user_valves) -> "Pipe.Valves":
        """
        Merge user-level valves into default.
        Ignores any user value set to "INHERIT" (case-insensitive).
        """
        if not user_valves:
            return global_valves

        # Merge: update only fields not set to "INHERIT"
        update = {
            k: v
            for k, v in user_valves.model_dump().items()
            if v is not None and str(v).lower() != "inherit"
        }
        return global_valves.model_copy(update=update)

    ###########################################################################################################

    async def _emit_error(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]],
        error_obj: Exception | str,
        *,
        show_error_message: bool = True,
        show_error_log_citation: bool = False,
        done: bool = False,
    ) -> None:
        """
        Logs the error and optionally emits data to the front-end UI.
        If 'citation' is True, also emits the debug logs for the current session_id.
        """
        error_message = str(error_obj)  # If it's an exception, convert to string
        self.log.error("Error: %s", error_message)

        if show_error_message and event_emitter:
            await event_emitter(
                {
                    "type": "chat:completion",
                    "data": {
                        "error": {
                            "message": error_message,
                        },
                    },
                }
            )

            # 2) Optionally emit the citation with logs
            if show_error_log_citation:
                msg_id = current_session_id.get()
                logs = logs_by_msg_id.get(msg_id, [])
                if logs:
                    await self._emit_citation(
                        event_emitter,
                        "\n".join(logs),
                        "Error Logs",
                    )
                else:
                    self.log.warning(
                        "No debug logs found for session_id %s", msg_id
                    )

    async def _emit_citation(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        document: str | list[str],
        source_name: str,
    ) -> None:
        """Emit a citation event to the UI if an emitter is provided."""
        if event_emitter is None:
            return

        if isinstance(document, list):
            doc_text = "\n".join(document)
        else:
            doc_text = document

        await event_emitter(
            {
                "type": "citation",
                "data": {
                    "document": [doc_text],
                    "metadata": [
                        {
                            "date_accessed": datetime.datetime.now().isoformat(),
                            "source": source_name,
                        }
                    ],
                    "source": {"name": source_name},
                },
            }
        )

    async def _emit_completion(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        *,
        content: str | None = "",                       # always included (may be "").  UI will stall if you leave it out.
        title:   str | None = None,                     # optional title.
        usage:   dict[str, Any] | None = None,          # optional usage block
        done:    bool = True,                           # True → final frame
    ) -> None:
        """Emit a chat:completion event to the UI if possible."""
        if event_emitter is None:
            return

        # Note: Open WebUI emits a final "chat:completion" event after the stream ends, which overwrites any previously emitted completion events' content and title in the UI.
        await event_emitter(
            {
                "type": "chat:completion",
                "data": {
                    "done": done,
                    "content": content,
                    **({"title": title} if title is not None else {}),
                    **({"usage": usage} if usage is not None else {}),
                }
            }
        )

    async def _emit_status(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        description: str,
        *,
        done: bool = False,
        hidden: bool = False,
    ) -> None:
        """Emit a status event to the UI if possible."""
        if event_emitter is None:
            return
        
        await event_emitter(
            {
                "type": "status",
                "data": {"description": description, "done": done, "hidden": hidden},
            }
        )

    async def _emit_notification(
        self,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None,
        content: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
    ) -> None:
        """Emit a toast notification event to the UI if possible."""
        if event_emitter is None:
            return

        await event_emitter(
            {"type": "notification", "data": {"type": level, "content": content}}
        )

    async def _get_or_create_aiohttp_session(self) -> aiohttp.ClientSession:
        """
        Get or create a reusable aiohttp.ClientSession with sane defaults.
        Call once in `pipes()`; keep it for the life of the process.
        """
        # Reuse existing session if available and open
        if self.session is not None and not self.session.closed:
            self.log.debug("Reusing existing aiohttp.ClientSession")
            return self.session

        self.log.debug("Creating new aiohttp.ClientSession")

        # Configure TCP connector for connection pooling and DNS caching
        connector = aiohttp.TCPConnector(
            limit=50,  # Max total simultaneous connections
            limit_per_host=10,  # Max connections per host
            keepalive_timeout=75,  # Seconds to keep idle sockets open
            ttl_dns_cache=300,  # DNS cache time-to-live in seconds
        )

        # Set reasonable timeouts for connection and socket operations
        timeout = aiohttp.ClientTimeout(
            connect=30,  # Max seconds to establish connection
            sock_connect=30,  # Max seconds for socket connect
            sock_read=3600,  # Max seconds for reading from socket (1 hour)
        )

        # Use orjson for fast JSON serialization
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            json_serialize=lambda obj: orjson.dumps(obj).decode(),
        )

        return session
    
    @staticmethod
    def set_function_calling_to_native(model_id: str) -> None:
        """
        Updates only the 'function_calling' field in params, setting it to 'native'.
        Also updates 'updated_at'.
        """
        with get_db() as db:
            row = db.query(Model).filter(Model.id == model_id).one_or_none()
            if not row:
                return  # Model doesn't exist

            # Make sure params is a dict
            row.params = row.params or {}

            # If it's already 'native', nothing else to do
            if row.params.get("function_calling") == "native":
                return

            # Update just this one field
            row.params["function_calling"] = "native"

            # Bump the updated_at timestamp
            row.updated_at = int(time.time())

            db.commit()   # Write changes
            db.refresh(row)  # optional, if you need the updated row


    @staticmethod
    def transform_tools_for_responses_api(tools_dict: dict[str, dict]) -> list[dict]:
        """
        Convert the internal 'tools_dict' from get_tools(...) into 
        an array of tool definitions for the OpenAI Responses API.

        NOTE: We rely on __tools__ (server-injected) instead of body["tools"], 
        because __tools__ is always provided, whereas body["tools"] is only set 
        if native function calling is enabled by the user. 
        """
        if not tools_dict:
            return []

        items = []
        for name, data in tools_dict.items():
            spec = data.get("spec", {})
            items.append({
                "type": "function",
                "name": spec.get("name", name),
                "description": spec.get("description", ""),
                "parameters": spec.get("parameters", {}),
                "strict": False # Revisit in future if I can get strict working (or if I should at all)
            })
        return items

    @staticmethod
    def web_search_tool(valves) -> dict:
        """Build a web_search tool dictionary."""
        return {"type": "web_search", "search_context_size": valves.SEARCH_CONTEXT_SIZE}

    @staticmethod
    def image_generation_tool(valves) -> dict:
        """Build an image_generation tool dictionary."""
        tool = {
            "type": "image_generation",
            "quality": valves.IMAGE_QUALITY,
            "size": valves.IMAGE_SIZE,
            "response_format": valves.IMAGE_FORMAT,
            "background": valves.IMAGE_BACKGROUND,
        }
        if valves.IMAGE_COMPRESSION:
            tool["output_compression"] = valves.IMAGE_COMPRESSION
        return tool

# ----------------------------------------------------------------------------------------------------
#  Public helpers ─ mirror Chats.* naming style
# ----------------------------------------------------------------------------------------------------
"""
Helpers to persist OpenAI responses safely in Open WebUI DB without impacting other
chat data. This allows us to store function call traces, tool outputs, and other
special items related to messages in a structured way, enabling easy retrieval
and reconstruction of conversations with additional context.

Schema Overview
---------------
Inside each chat document (`chat_model.chat`), we store an `openai_responses_pipe` structure:

    {
      "openai_responses_pipe": {
        "__v": 2,                           # version

        "messages": {
          "<message_id>": {
            "model": "o4-mini",          # stamped once – avoids per-item duplication
            "created_at": 1719922512,    # unix-seconds the root message arrived

            "items": [ /* raw output items in arrival order */ ]
          }
        },
      }
    }

When users or the system perform a function call (or any special action)
related to a message, we append these "response items" to
`openai_responses_pipe.messages[<message_id>]`. Later, when reconstructing
the conversation, these items can be inserted above the respective message
that triggered them. This allows for easy referencing of function calls,
their outputs, or any other extra JSON data in the final conversation flow.
"""

def add_openai_response_items_to_chat_by_id_and_message_id(
    chat_id: str,
    message_id: str,
    items: List[Dict[str, Any]],
    model_id: str,
) -> Optional[ChatModel]:
    """
    Append JSON-serializable items under chat.openai_responses_pipe.messages[message_id].
    Returns the updated ChatModel or None if the chat is not found.
    """
    if not items:
        return Chats.get_chat_by_id(chat_id)  # nothing to add

    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return None

    pipe_root = chat_model.chat.setdefault("openai_responses_pipe", {"__v": 2})
    messages_dict = pipe_root.setdefault("messages", {})

    bucket = messages_dict.setdefault(
        message_id,
        {
            "model": model_id,
            "created_at": int(datetime.datetime.utcnow().timestamp()),
            "items": [],
        },
    )
    bucket.setdefault("model", model_id)
    bucket.setdefault("created_at", int(datetime.datetime.utcnow().timestamp()))
    bucket.setdefault("items", [])
    bucket["items"].extend(items)

    return Chats.update_chat_by_id(chat_id, chat_model.chat)


def get_openai_response_items_by_chat_id_and_message_id(
    chat_id: str,
    message_id: str,
    *,
    type_filter: Optional[str] = None,
    model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return stored items from chat.openai_responses_pipe.messages[message_id].
    If type_filter is given, only items whose 'type' matches are returned.
    """
    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return []

    bucket = (
        chat_model.chat
        .get("openai_responses_pipe", {})
        .get("messages", {})
        .get(message_id, {})
    )

    if model_id and bucket.get("model") != model_id:
        return []

    all_items = bucket.get("items", [])
    if not type_filter:
        return all_items
    return [x for x in all_items if x.get("type") == type_filter]

def remove_details_tags_by_type(text: str, removal_types: list[str]) -> str:
    """
    Removes any <details> tag whose type attribute is in `removal_types`.
    Example:
      remove_details_tags_by_type("Hello <details type='reasoning'>stuff</details>", ["reasoning"])
      => "Hello "
    """
    # Safely escape the types in case they have special regex chars
    pattern_types = "|".join(map(re.escape, removal_types))
    # Example pattern: <details type="reasoning">...</details>
    pattern = rf'<details\b[^>]*\btype=["\'](?:{pattern_types})["\'][^>]*>.*?</details>'
    return re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)

def build_responses_history_by_chat_id_and_message_id(
    chat_id: str,
    message_id: Optional[str] = None,
    *,
    model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return a list of messages + any stored pipe items, up to `message_id`.
    Minimal version:
      - If chat_id doesn't exist, return empty.
      - Build chain from root to message_id.
      - Insert any "pipe" items before the corresponding message.
      - Wrap each message's content as a single text block.
    """

    # 1. Fetch the chat, exit if not found
    chat_model = Chats.get_chat_by_id(chat_id)
    if not chat_model:
        return []

    chat_data = chat_model.chat

    # 2. Determine message_id (default: currentId from history)
    if not message_id:
        message_id = chat_data.get("history", {}).get("currentId")

    # 3. Gather message chain (root → message_id)
    hist_dict = chat_data.get("history", {}).get("messages", {})
    chain = get_message_list(hist_dict, message_id)
    if not chain:
        return []

    # 4. Retrieve any pipe messages
    pipe_messages = (
        chat_data
        .get("openai_responses_pipe", {})
        .get("messages", {})
    )

    final: List[Dict[str, Any]] = []

    # 5. For each message in the chain
    for msg in chain:
        msg_id = msg["id"]

        # 5a. Insert openai_responses_pipe items (function calls, etc.) first if they exist
        bucket = pipe_messages.get(msg_id, {})
        if bucket and (not model_id or bucket.get("model") == model_id):
            extras = bucket.get("items", [])
            final.extend(extras)

        # 5b. Add the main message
        role = msg.get("role", "assistant")
        text_content = msg.get("content", "")

        # Build the final message structure
        final.append({
            "type": "message",
            "role": role,
            "content": [
                {
                    "type": "input_text" if role == "user" else "output_text",
                    "text": text_content.strip()
                }
            ]
        })

    return final


## Miscellaneous Helpers
def update_usage_totals(total, new):
    for k, v in new.items():
        if isinstance(v, dict):
            total[k] = update_usage_totals(total.get(k, {}), v)
        elif isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v
        else:
            # Skip or explicitly set non-numeric values
            total[k] = v if v is not None else total.get(k, 0)
    return total
