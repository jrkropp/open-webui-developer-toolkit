"""
title: OpenAI Responses API Pipeline
id: openai_responses_api_pipeline
author: Justin Kropp
author_url: https://github.com/jrkropp
description: Brings OpenAI Response API support to Open WebUI, enabling features not possible via Completions API.
version: 1.6.9
license: MIT
requirements: openai>=1.78.0

Test123

------------------------------------------------------------------------------------------------------------------------
📌 OVERVIEW
------------------------------------------------------------------------------------------------------------------------
This pipeline brings OpenAI Responses API with Open WebUI, enabling features not possible via Completions API.

Key Features:
   1) Supports o3/o4-mini reasoning models (including visible <think> reasoning summaries)
   2) Image input support (output support coming soon...)
   3) Optional built-in web search tool (powered by OpenAI web_search tool)
   4) Usage stats passthrough (to OpenWebUI GUI)
   5) Supports cache pricing (up to 75% discount for input tokens that hit OpenAI Cache)
   6) Support LiteLLM and other Response API compatible gateways.
   7) Optimized native tool calling:
        - True parallel tool calling support (i.e., gather multiple tool calls within a single turn and execute in parallel)
        - Status emitters show which tool(s) the model is calling
        - Tool results are emitted as citations for traceability & transparancy.
        - Tool results are retained in conversation history (function_call/function_call_output) so users can ask follow up questions
        - Retain reasoning tokens across tool turns (loops).
            o3/o4-mini internal reasoning tokens aren't externally visible and therefore can't be passed back into the model.
            To work around this, the pipe temporarily uses previous_response_id to retain context within tool turn loops.
            This allows reasoning models to call turns mid-reasoning, get tool result and continue reasoning.
            This is ONLY possible with the responses API and sigificantly improves speed, reduces cost (since model doesn't need
            to re-reasoning) and improved ability.

Future Improvements:
   TODO - Image output support
   TODO - Document input support (e.g., PDFs, other files via __files__ parameter in pipe() function).
   TODO - Consider adding support for file_search (built-in OpenAI tool)

Notes:
   - This pipeline is experimental. USE AT YOUR OWN RISK.
   - Duplicate/clone this pipeline if you want multiple models.
   - Tool calling requires 'OpenWebUI Model Advanced Params → Function Calling → set to "Native"'

Read more about OpenAI Responses API:
- https://openai.com/index/new-tools-for-building-agents/
- https://platform.openai.com/docs/quickstart?api-mode=responses
- https://platform.openai.com/docs/api-reference/responses

-----------------------------------------------------------------------------------------
🛠️ CHANGELOG
-----------------------------------------------------------------------------------------
• 1.6.9 (2025-05-12)
    - Updated requirements to "openai>=1.78.0" (library will automatically install when pipe in initialized).
    - Added UserValves class to allow users to override system valve settings.
    - Improved logging
• 1.6.8 (2025-05-09)
    - Improved logging formating and control. Replaced DEBUG (on/off) valve with more granular CUSTOM_LOG_LEVEL (DEBUG/INFO/WARNING/ERROR).
    - Refactored code for improved readability and maintainability.
• 1.6.7
    - Increased timeout from 90sec -> 900sec to better account for the o3 model which might take minutes before a response.
    - Updated requirements to "openai>=1.77.0" (library will automatically install when pipe in initialized).
• 1.6.6
    - Added support for usage statistics in OpenWebUI UI. Added aggregated token-usage reporting (with loop count) so WebUI's ℹ pop-over shows correct totals even when the model makes multiple tool-call turns.
• 1.6.5
    - Adjusted formating of citation output to include the arguments and output of the function call in the citation.  This is useful for debugging and transparency.
    - Fixed system-prompt extractor to properly process template variables and honor user-defined prompts over the default defined in the model settings.
• 1.6.4
   - Fixed thinking tags so it won't output multiple <think> tags in a row (applies to o3-mini)
• 1.6.3
   - Added valve option to enable persistant tool results to the conversation history.  This allows the model to remember tool outputs across requests.
• 1.6.2
   - Fixed bug where it would check if the client is established each time a chunk is streamed.  Fixed by moving, 'client = get_openai_client(self.valves)' outside the while loop.
• 1.6.1
   - Updated requirements to "openai>=1.76.0" (library will automatically install when pipe in initialized).
   - Added lazy and safe OpenAI client creation inside pipe() to avoid unnecessary re-instantiation.
   - Cleaned up docstring for improved readability.
• 1.6.0
   - Added TOKEN_BUFFER_SIZE (default 1) for streaming control. This controls the number of tokens to buffer before yielding. Set to 1 for immediate per-token streaming.
   - Cleaned up docstring at top of file for better readability.
   - Refactored code for improved readability and maintainability.
   - Rewrote transform_chat_messages_to_responses_api_format() for better readability and performance.
   - Changed tool_choice behavior.  Now defaults to "none" if no tools are present.
• 1.5.10
   - Introduced True Parallel Tool Calling. Tool calls are now executed in parallel using asyncio.gather, then all results are appended at once before returning to the LLM. Previously, calls were handled one-by-one due to sequential loop logic.
   - Set PARALLEL_TOOL_CALLS default back to True to match OpenAI's default behavior.
   - The model now receives a clear system message when nearing the MAX_TOOL_CALLS limit, encouraging it to conclude tool use gracefully.
   - Status messages now reflect when a tool is being invoked, with more personality and clarity for the user.
   - Tool responses are now emitted as citations, giving visibility into raw results (especially useful for debugging and transparency).
• 1.5.9
   - Fixed bug where web_search tool could cause OpenAI responses to loop indefinitely.
   - Introduced MAX_TOOL_CALLS valve (default 5) to limit the number of tool calls in a single request as extra safety precaution.
   - Set PARALLEL_TOOL_CALLS valve default to False (prev. True).
• 1.5.8
   - Polished docstrings and streamlined debug logging output.
   - Refactored code for improved readability.
• 1.5.7
   - Introduced native tool support for OpenAI! Integrate with OpenWebUI tools.
• 1.5.6
   - Fixed minor bugs in function calling and improved performance for large messages.
   - Introduced partial support for multi-modal input.
"""

from __future__ import annotations

# Core & third-party imports
import os, re, json, uuid, time, asyncio, traceback, sys, logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Awaitable, Literal, ClassVar

import httpx
import time
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from fastapi import Request

# Internal imports
from open_webui.models.chats import Chats
from pydantic import BaseModel, Field


###############################################################################
# 3. Main Pipe Class
###############################################################################
class Pipe:
    """
    A pipeline for streaming responses from the OpenAI Responses API.
    """

    class Valves(BaseModel):
        BASE_URL: str = Field(
            default="https://api.openai.com/v1",
            description="The base URL to use with the OpenAI SDK. Defaults to the official OpenAI API endpoint. Supports LiteLLM and other custom endpoints.",
        )

        API_KEY: str = Field(
            default=os.getenv(
                "OPENAI_API_KEY", "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            ),
            description=(
                "Your OpenAI API key. Defaults to the value of the OPENAI_API_KEY environment variable. "
            ),
        )

        MODEL_ID: str = Field(
            default="gpt-4.1",
            description=(
                "Model ID used to generate responses. Defaults to 'gpt-4.1'. Note: The model ID must be a valid OpenAI model ID. E.g. 'gpt-4o', 'o3', etc."
            ),
        )  # Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-model

        REASON_SUMMARY: Literal["auto", "concise", "detailed", None] = Field(
            default=None,
            description=(
                "Reasoning summary style for o-series models (if your OpenAI org has access). OpenAI may require identify verification before enabling. Leave blank to disable (default)."
            ),
        )  # Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-reasoning

        REASON_EFFORT: Literal["low", "medium", "high", None] = Field(
            default=None,
            description=(
                "Reasoning effort level for o-series models. "
                "Leave blank to disable (default)."
            ),
        )  # Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-reasoning

        ENABLE_WEB_SEARCH: bool = Field(
            default=False,
            description=(
                "Whether to enable OpenAI's built-in 'web_search' tool. If True, adds {'type': 'web_search'} to tools (unless already present). Note: Tool occurs additional charge each time the model calls it"
            ),
        )  # Read more: https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses

        SEARCH_CONTEXT_SIZE: Literal["low", "medium", "high", None] = Field(
            default="medium",
            description=(
                "Specifies the OpenAI web search context size: low | medium | high. Default is 'medium'. Affects cost, quality, and latency. Only used if ENABLE_WEB_SEARCH=True."
            ),
        )
        PARALLEL_TOOL_CALLS: bool = Field(
            default=True,
            description=(
                "Whether tool calls can be parallelized. Defaults to True if not set."
            ),
        )  # Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-parallel_tool_calls

        # TODO Need to rename as it's not truely max tool calls.  It's max tool loops.  It can call an unlimited number of tools within a single loop.
        MAX_TOOL_CALLS: int = Field(
            default=5,
            description=(
                "Maximum number of tool calls the model can make in a single request. This is a hard stop safety limit to prevent infinite loops. Defaults to 5."
            ),
        )

        STORE_RESPONSE: bool = Field(
            default=False,
            description=(
                "Whether to store the generated model response (on OpenAI's side) for later debuging. Defaults to False."
            ),
        )  # Read more: https://platform.openai.com/docs/api-reference/responses/create#responses-create-store

        CUSTOM_LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = (
            Field(
                default=os.getenv("GLOBAL_LOG_LEVEL", "INFO").upper(),
                description="Select logging level.",
            )
        )

    class UserValves(BaseModel):
        CUSTOM_LOG_LEVEL: Literal[
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "INHERIT"
        ] = Field(
            default="INHERIT",
            description="Select logging level. Set to 'INHERIT' to use the system default.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.name = f"OpenAI: {self.valves.MODEL_ID}"  # TODO fix this as MODEL_ID value can't be accessed from within __init__.

        # OpenAI Client
        self._transport: httpx.AsyncClient | None = None
        self._client: AsyncOpenAI | None = None
        self._client_lock = asyncio.Lock()

        # Set up logging
        self.log = logging.getLogger(self.name)
        self.log.propagate = False  # prevent root interference
        emoji = {
            logging.DEBUG: "🔍",
            logging.INFO: "ℹ️",
            logging.WARNING: "⚠️",
            logging.ERROR: "❌",
            logging.CRITICAL: "🔥",
        }
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.NOTSET)
        handler.addFilter(
            lambda r: setattr(r, "emo", emoji.get(r.levelno, "🔹")) or True
        )
        handler.setFormatter(
            logging.Formatter(
                "%(emo)s %(levelname)-8s | %(name)-20s:%(lineno)-4d — %(message)s"
            )
        )
        self.log.handlers = [handler]

        pass

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        # Clean up OpenAI Client
        if self._client and not self._client._closed:
            await self._transport.aclose()
            self._client = None
            self._transport = None
        pass

    async def on_valves_updated(self):
        pass

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: Dict[str, Any],
        __request__: Request,
        __event_emitter__: Callable[["Event"], Awaitable[None]],
        __event_call__: Callable[[dict[str, Any]], Awaitable[Any]],
        __files__: list[dict[str, Any]],
        __metadata__: dict[str, Any],
        __tools__: dict[str, Any],
    ):
        # ─────────────────── Pre-Pipe Checks and Setup ───────────────────
        start_ns = time.perf_counter_ns()

        # Copy user valve overrides into self.valves, skipping if value = None / "inherit"
        user_valves = __user__.get("valves")
        if user_valves:
            for setting, user_val in user_valves.model_dump(exclude_none=True).items():
                if (
                    isinstance(user_val, str) and user_val.lower() == "inherit"
                ):  # skip if value is "inherit"
                    continue
                setattr(self.valves, setting, user_val)
                self.log.debug("User override → %s set to %r", setting, user_val)

        # Update Log Level
        self.log.setLevel(
            getattr(
                logging, self.valves.CUSTOM_LOG_LEVEL.upper() or "INFO", logging.INFO
            )
        )

        # Warn user if tools are provided, but function calling is not 'native'.
        if __tools__ and __metadata__.get("function_calling") != "native":
            yield "🛑 Tools detected, but native function calling is disabled.\n\nTo enable tools in this chat, switch **Function Calling** to **'Native'** under:\n⚙️ **Chat Controls** → **Advanced Params** → **Function Calling**\n\nIf you're an admin, you can also set this at the **model level**:\n**Model Settings** → **Advanced Params** → **Function Calling = Native**"
            self.log.error("Tools detected, but native function calling is disabled.")
            return

        # ─────────────────── Main Pipeline Loop ──────────────────────────
        self.log.info(
            'CHAT_MSG pipe="%s" m=%s u=%s ip=%s chat=%s sess=%s msg=%s msgs=%d tools=%s',
            self.name,
            self.valves.MODEL_ID,
            __user__.get("email", "anon"),
            __request__.headers.get("x-envoy-external-address", "-"),
            __metadata__["chat_id"],
            __metadata__["session_id"],
            __metadata__["message_id"],
            len(body["messages"]),
            ",".join(__metadata__.get("tool_ids", [])) or "-",
        )

        # STEP 1: Establish OpenAI Client (if one doesn't already exist)
        client = await self.get_openai_client()

        # STEP 2: Transform the user’s messages into the format the Responses API expects
        # TODO Consider setting the user system prompt (if specified) as a developer message rather than replacing the model system prompt.  Right now it get's the last instance of system message (user system prompt takes precidence)
        chat_id = __metadata__["chat_id"]  # always present
        input_messages = build_responses_payload(chat_id)  # get the current chat thread
        instructions = next(
            (
                msg.get("content")
                for msg in reversed(body.get("messages", []))
                if msg.get("role") == "system"
            ),
            "",
        )

        # STEP 3: Prepare any tools (function specs), if any
        tools = prepare_tools(__tools__)
        if self.valves.ENABLE_WEB_SEARCH:
            tools.append(
                {
                    "type": "web_search",
                    "search_context_size": self.valves.SEARCH_CONTEXT_SIZE,
                }
            )

        self.log.debug(pretty_log_block(tools, "tools"))
        self.log.debug(pretty_log_block(instructions, "instructions"))
        self.log.debug(pretty_log_block(input_messages, "input_messages"))

        # STEP 4: Build the request parameters
        request_params = {
            "model": self.valves.MODEL_ID,
            "tools": tools,
            "tool_choice": "auto" if tools else "none",
            "instructions": instructions,
            "parallel_tool_calls": self.valves.PARALLEL_TOOL_CALLS,
            "max_output_tokens": body.get("max_tokens"),
            "temperature": body.get("temperature") or 1.0,
            "top_p": body.get("top_p") or 1.0,
            "user": __user__.get("email"),
            "text": {"format": {"type": "text"}},
            "truncation": "auto",
            "stream": True,
        }

        if self.valves.REASON_EFFORT or self.valves.REASON_SUMMARY:
            request_params["reasoning"] = {}
            if self.valves.REASON_EFFORT:
                request_params["reasoning"]["effort"] = self.valves.REASON_EFFORT
            if self.valves.REASON_SUMMARY:
                request_params["reasoning"]["summary"] = self.valves.REASON_SUMMARY

        usage_total = {}
        is_model_thinking = False
        last_response_id = None
        temp_input = []

        # STEP 5: Loop until we either run out of tool calls or the conversation ends (one extra loop for safety)
        for loop_count in range(1, self.valves.MAX_TOOL_CALLS + 1):
            self.log.debug("Loop iteration #%d", loop_count)

            if loop_count == 1:
                # ── A. First loop: send the initial request to OpenAI Responses API ──
                request_params["store"] = True
                request_params["input"] = input_messages
            else:
                # ── B. Subsequent loops: send the previous response ID and temp_input ──
                request_params["store"] = True
                request_params["previous_response_id"] = last_response_id
                request_params["input"] = temp_input
                self.log.debug(pretty_log_block(temp_input, "temp_input"))
                temp_input = []  # reset for next iteration

            try:
                # ── C. Create the streaming request and process events ───────────────
                pending_function_calls = []
                response_stream = await client.responses.create(**request_params)
                self.log.debug("response_stream created for loop #%d", loop_count)

                async for event in response_stream:
                    event_type = event.type
                    self.log.debug("Event received: %s", event_type)

                    # ─────────────────── Lifecycle & errors ───────────────────
                    if event_type in {"response.created"}:
                        last_response_id = event.response.id
                        continue
                    if event_type in {
                        "response.done",
                        "response.failed",
                        "response.incomplete",
                        "error",
                    }:
                        # TODO add some logging here.  Errors should be logged as errors.
                        break

                    # ─────────────────── Reasoning Summary Text ────────────────────
                    if event_type == "response.reasoning_summary_part.added":
                        if is_model_thinking == False:
                            is_model_thinking = True
                            yield "<think>"
                        continue

                    if event_type == "response.reasoning_summary_text.delta":
                        yield event.delta
                        continue

                    if event_type == "response.reasoning_summary_text.done":
                        yield "\n\n---\n\n"  # Add a line break in-between reasoning summaries

                        # append the reasoning item so the next turn remembers it
                        request_params["input"].append(
                            {  # the reasoning summary
                                "type": "reasoning",
                                "id": event.item_id,
                                "summary": [
                                    {"type": "summary_text", "text": event.text}
                                ],
                            }
                        )
                        continue

                    # ─────────────────── Assistant output text ──────────────────────
                    if event_type == "response.content_part.added":
                        if is_model_thinking == True:
                            is_model_thinking = False
                            yield "</think>\n"
                        continue

                    if event_type == "response.output_text.delta":
                        yield event.delta
                        continue

                    if event_type == "response.output_text.done":
                        # TODO is this still needed now that I retain message context using previous_response_id?
                        request_params["input"].append(
                            {
                                "role": "assistant",
                                "content": [
                                    {"type": "output_text", "text": event.text}
                                ],
                            }
                        )
                        continue

                    # ─────────────────── Function Call ──────────────────────
                    if event_type == "response.output_item.added":
                        item = getattr(event, "item", None)
                        item_type = getattr(item, "type", None)

                        if item_type == "function_call":
                            await __event_emitter__(
                                {
                                    "type": "status",
                                    "data": {
                                        "description": f"🔧 Hmm, let me run my {item.name} tool ...",
                                        "done": False,
                                    },
                                }
                            )
                        elif item_type == "web_search_call":
                            await __event_emitter__(
                                {
                                    "type": "status",
                                    "data": {
                                        "description": f"🔍 Searching the internet...",
                                        "done": False,
                                    },
                                }
                            )
                        continue

                    if event_type == "response.output_item.done":
                        item = getattr(event, "item", None)
                        item_type = getattr(item, "type", None)

                        if item_type == "function_call":
                            pending_function_calls.append(
                                item
                            )  # add to pending function calls

                            # TODO consider removing this.  It can look strange where there are back to back calls and it rapidly flashes and clears.
                            await __event_emitter__(
                                {
                                    "type": "status",
                                    "data": {
                                        "description": "",
                                        "done": True,
                                    },
                                }
                            )
                        elif item_type == "web_search_call":
                            await __event_emitter__(
                                {
                                    "type": "status",
                                    "data": {
                                        "description": "",
                                        "done": True,
                                    },
                                }
                            )

                        continue

                    # ─────────────────── Citations / annotations ──────────────
                    if event_type == "response.output_text.annotation.added":
                        raw_anno = str(getattr(event, "annotation", ""))
                        title_m = re.search(r"title='([^']*)'", raw_anno)
                        url_m = re.search(r"url='([^']*)'", raw_anno)
                        title = title_m.group(1) if title_m else "Unknown Title"
                        url = url_m.group(1) if url_m else ""
                        url = url.replace("?utm_source=openai", "").replace(
                            "&utm_source=openai", ""
                        )
                        if __event_emitter__:
                            await __event_emitter__(
                                {
                                    "type": "citation",
                                    "data": {
                                        "document": [title],
                                        "metadata": [
                                            {
                                                "date_accessed": datetime.now().isoformat(),
                                                "source": title,
                                            }
                                        ],
                                        "source": {"name": url, "url": url},
                                    },
                                }
                            )
                        continue

                    if event.type == "response.completed":
                        # ─────────────────── Usage stats ──────────────────────
                        if usage := event.response.usage:
                            usage_dict = usage.model_dump()
                            usage_dict["loops"] = loop_count

                            # Accumulate totals
                            for key, current_value in usage_dict.items():
                                if key == "loops":
                                    continue
                                if isinstance(current_value, int):
                                    usage_total[key] = (
                                        usage_total.get(key, 0) + current_value
                                    )
                                elif isinstance(current_value, dict):
                                    if key not in usage_total:
                                        usage_total[key] = {}
                                    for subkey, subval in current_value.items():
                                        usage_total[key][subkey] = (
                                            usage_total[key].get(subkey, 0) + subval
                                        )

                            usage_total["loops"] = loop_count

                            # Yield the cumulative total so far.
                            yield {"usage": usage_total}
                        continue

            except Exception as ex:
                self.log.error("Error in pipeline loop #%d: %s", loop_count, ex)
                yield f"❌ {type(ex).__name__}: {ex}\n{''.join(traceback.format_exc(limit=5))}"
                break

            # ---------------------------------------------------------------------------
            # 3) We have function-calls pending → run them, emit citation metadata, loop
            # ---------------------------------------------------------------------------
            if pending_function_calls:
                tasks: list[asyncio.Task] = []

                # ── A. schedule each tool and push its function-call stub into context ──
                for fc_item in pending_function_calls:
                    tool_entry = __tools__.get(fc_item.name)
                    if tool_entry is None:
                        # skip missing tool but keep a placeholder result
                        tasks.append(
                            asyncio.create_task(
                                asyncio.sleep(0, result="Tool not found")
                            )
                        )

                    else:
                        args = json.loads(fc_item.arguments or "{}")
                        tasks.append(
                            asyncio.create_task(tool_entry["callable"](**args))
                        )

                # ── B. wait for all tools to finish ────────────────────────────────────
                try:
                    results = await asyncio.gather(*tasks)
                except Exception as ex:
                    results = [f"Error: {ex}"] * len(tasks)

                # ── C. emit function_call_output + rich citation metadata ──────────────
                for call, result in zip(pending_function_calls, results):
                    # Prepare function call data
                    call_entry = {
                        "type": "function_call",
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }

                    output_entry = {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": str(result),
                    }

                    # Add entries to request params
                    request_params["input"].append(call_entry)
                    request_params["input"].append(output_entry)

                    # Place tool outputs at the TOP of next iteration's context:
                    temp_input.insert(0, output_entry)

                    # Log the function call and output
                    self.log.debug(
                        pretty_log_block(
                            {**call_entry, **output_entry}, "function_call"
                        )
                    )

                    # Emit citation event if emitter is provided
                    if __event_emitter__:
                        citation_event = {
                            "type": "citation",
                            "data": {
                                "document": [
                                    f"{call.name}({call.arguments})\n\n{result}"
                                ],
                                "metadata": [
                                    {
                                        "date_accessed": datetime.now().isoformat(),
                                        "source": call.name.replace("_", " ").title(),
                                    }
                                ],
                                "source": {
                                    "name": f"{call.name.replace('_', ' ').title()} Tool"
                                },
                                # TODO is there a better way to store tool results in conversation history?
                                "_fc": [
                                    {
                                        "call_id": call.call_id,
                                        "name": call.name,
                                        "arguments": call.arguments,
                                        "output": str(result),
                                    }
                                ],
                            },
                        }
                        await __event_emitter__(citation_event)

                continue  # Continue main streaming loop
            else:
                # Clean up the server-side state unless the user opted to keep it

                # TODO Ensure that the stored response is deleted.  Doesn't seem to work with LiteLLM Response API.
                """
                if last_response_id and not self.valves.STORE_RESPONSE:
                    try:
                        await client.responses.delete(last_response_id)
                        self.log.debug("Deleted response %s", last_response_id)
                    except Exception as ex:
                        self.log.warning("Could not delete response %s: %s",
                                        last_response_id, ex)
                """
                remaining = self.valves.MAX_TOOL_CALLS - loop_count

                if loop_count == self.valves.MAX_TOOL_CALLS:
                    request_params["tool_choice"] = "none"
                    temp_input.append(
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        f"[Internal thought] Final iteration ({loop_count}/{self.valves.MAX_TOOL_CALLS}). "
                                        "Tool-calling phase is over; I'll produce my final answer now."
                                    ),
                                }
                            ],
                        }
                    )
                    self.log.debug("Injected final-iteration notice.")

                elif loop_count == 2 and self.valves.MAX_TOOL_CALLS > 2:
                    temp_input.append(
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        f"[Internal thought] I've just received the initial tool results from iteration 1. "
                                        f"I'm now continuing an iterative tool interaction with up to {self.valves.MAX_TOOL_CALLS} iterations.\n"
                                        "- Each iteration re-evaluates the entire conversation (including previous tool outputs), "
                                        "meaning extra iterations cost more tokens and reduce efficiency.\n"
                                        "- I'll batch as many required tool calls as possible right now to stay efficient.\n"
                                        "- The final iteration is reserved exclusively for my final answer—no tools allowed."
                                    ),
                                }
                            ],
                        }
                    )

                elif remaining == 1:
                    temp_input.append(
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        f"[Internal thought] Iteration {loop_count}/{self.valves.MAX_TOOL_CALLS}. "
                                        "Next iteration is answer-only; any remaining tool calls must happen now."
                                    ),
                                }
                            ],
                        }
                    )

                elif loop_count > 2:
                    temp_input.append(
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        f"[Internal thought] Iteration {loop_count}/{self.valves.MAX_TOOL_CALLS} "
                                        f"({remaining} remaining, no action needed)."
                                    ),
                                }
                            ],
                        }
                    )

                self.log.debug("No pending function calls. Ending pipeline loop.")
                break  ## no more function calls pending

        # ── END OF WHILE LOOP ───────────────────────────────────────────────────────
        self.log.info(
            "CHAT_DONE chat=%s dur_ms=%.0f loops=%d in_tok=%d out_tok=%d total_tok=%d",
            __metadata__["chat_id"],
            (time.perf_counter_ns() - start_ns) / 1e6,
            usage_total.get("loops", 1),
            usage_total.get("input_tokens", 0),
            usage_total.get("output_tokens", 0),
            usage_total.get("total_tokens", 0),
        )

    async def get_openai_client(self) -> AsyncOpenAI:
        self.log.debug("Checking cached OpenAI client...")

        if self._client and self._transport and not self._transport.is_closed:
            self.log.debug("Reusing existing OpenAI client and transport.")
            return self._client

        async with self._client_lock:
            self.log.debug("Acquired client lock.")

            if self._client and self._transport and not self._transport.is_closed:
                self.log.debug(
                    "Client initialized while waiting for lock. Reusing existing."
                )
                return self._client

            if self._transport and not self._transport.is_closed:
                self.log.debug("Closing existing transport before reinitializing.")
                await self._transport.aclose()

            self.log.debug("Creating new httpx.AsyncClient transport.")
            self._transport = httpx.AsyncClient(http2=True, timeout=900)

            self.log.debug("Initializing AsyncOpenAI client.")
            self._client = AsyncOpenAI(
                api_key=self.valves.API_KEY,
                base_url=self.valves.BASE_URL,
                http_client=self._transport,
            )

            self.log.debug("OpenAI client initialized and cached.")
            return self._client


###############################################################################
# Module-level Helper Functions (Outside Pipe Class)
###############################################################################
def prepare_tools(registry: dict | None) -> list[dict]:
    """
    Convert OpenWebUI's tool registry to the OpenAI Responses `tools=` payload.
    """
    if not registry:
        return []

    raw = registry.get("tools", registry)
    tools_out = []

    for entry in raw.values():
        spec = entry.get("spec", entry)
        if "function" in spec:  # unwrap {type:function,function:{…}}
            spec = spec["function"]
        tools_out.append(
            {
                "type": "function",
                "name": spec["name"],
                "description": spec.get("description", ""),
                "parameters": spec.get("parameters", {"type": "object"}),
            }
        )
    return tools_out


def build_responses_payload(chat_id: str) -> list[dict]:
    """
    Build the structured list expected by openai.responses.create().
    """
    chat = Chats.get_chat_by_id(chat_id).chat
    msg_lookup = chat["history"]["messages"]
    current_id = chat["history"]["currentId"]

    thread: list[dict] = []
    while current_id:
        msg = msg_lookup[current_id]
        thread.append(msg)
        current_id = msg.get("parentId")
    thread.reverse()  # oldest → newest

    input_items: list[dict] = []

    for m in thread:
        role = m["role"]
        from_assistant = role == "assistant"

        # Historical function calls
        if from_assistant:
            for src in m.get("sources", ()):
                for fc in src.get("_fc", ()):
                    cid = fc.get("call_id") or fc.get("id")
                    if not cid:
                        continue
                    input_items.append(
                        {
                            "type": "function_call",
                            "call_id": cid,
                            "name": fc.get("name") or fc.get("n"),
                            "arguments": fc.get("arguments") or fc.get("a"),
                        }
                    )
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": cid,
                            "output": fc.get("output") or fc.get("o"),
                        }
                    )

        # Visible content (text/files)
        blocks: list[dict] = []
        raw_blocks = m.get("content", []) or []
        if not isinstance(raw_blocks, list):
            raw_blocks = [raw_blocks]

        for b in raw_blocks:
            if b is None:
                continue
            text = b["text"] if isinstance(b, dict) else str(b)
            if from_assistant and not text.strip():
                continue
            blocks.append(
                {
                    "type": "output_text" if from_assistant else "input_text",
                    "text": text,
                }
            )

        # Images
        for f in m.get("files", ()):
            if f and f.get("type") in ("image", "image_url"):
                blocks.append(
                    {
                        "type": "input_image" if role == "user" else "output_image",
                        "image_url": f.get("url") or f.get("image_url", {}).get("url"),
                    }
                )

        if blocks:
            input_items.append({"role": role, "content": blocks})

    return input_items


def pretty_log_block(data: Any, label: str = "") -> str:
    try:
        content = json.dumps(data, indent=2, default=str)
    except Exception:
        content = str(data)

    label_line = f"{label} =" if label else ""
    return f"\n{'-' * 40}\n{label_line}\n{content}\n{'-' * 40}"
