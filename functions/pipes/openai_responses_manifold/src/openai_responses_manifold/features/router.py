"""Model routing helpers (e.g., GPT-5 auto selection)."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ..core import ResponsesBody, supports
from ..infra.client import OpenAIResponsesClient

logger = logging.getLogger(__name__)


async def route_gpt5_auto(
    client: OpenAIResponsesClient,
    router_model: str,
    responses_body: ResponsesBody,
    valves: Any,
    tools: list[dict[str, Any]],
    event_emitter: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> ResponsesBody:
    """Route GPT-5 auto requests via a lightweight helper model."""

    _ = tools, event_emitter, router_model  # not yet used but kept for parity
    router_body = {
        "model": "gpt-5-mini",
        "reasoning": {"effort": "minimal"},
        "instructions": '# Role and Objective\nServe as a **routing helper** for selecting the most appropriate GPT-5 model for user messages, evaluating tool necessity and task complexity.\n\n---\n\n# Instructions\n- If a message may require the use of **any available tool**, select a model with **function calling** capabilities. If **web search** is required, you may only choose **low, medium or high** reasoning, not minimal.\n- When tools are not necessary, favor the **fastest** or **most capable** model according to the complexity of the request.\n\n---\n\n# Available Models and Capabilities\n## Models\n\n- **gpt-5-chat-latest**\n  - Fast, general-purpose, and creative.\n  - Best for writing, drafting, and chat-based interactions.\n  - ⚠️ Does **not** support tool calling—select only when tools are not required.\n\n- **gpt-5-mini**\n  - Lightweight, supports tool usage, and is rapidly responsive.\n  - Suited for **simple tasks that may use tools** but don\'t demand extensive reasoning.\n  - ✅ Function calling supported—offers a strong balance between speed and utility.\n\n- **gpt-5**\n  - Strong at reasoning and complex, multi-step analysis.\n  - Designed for **complex or deeply analytical tasks**.\n  - ✅ Supports function calling and advanced operations—choose for tool-reliant or high-complexity reasoning needs.\n\n---\n\n# Routing Checklist\n- Assess whether tool integration could improve the response.\n- Evaluate how much reasoning or problem-solving is required.\n- Match model to requirements:\n  - No tool usage required → use `gpt-5-chat-latest`\n  - Tools required, simple task → use `gpt-5-mini`\n  - Tools required, complex task → use `gpt-5`\n- When in doubt, prioritize a tool-capable model (prefer `gpt-5`).\n- Ask for more information if requirements are ambiguous.\n\n---\n\n# Output Format\nRespond only with a JSON object containing your model selection and a concise explanation. If the requirements are unclear, include an appropriate error message in the JSON response.\n\n---\n\n# Examples\n- **What\'s the weather in Vancouver right now?**\n  ```json\n  {\n    "model": "gpt-5-mini",\n    "explanation": "Quick tool lookup; simple enough for a fast model."\n  }\n  ```\n\n- **Compare the newest M3 laptops and cite sources.**\n  ```json\n  {\n    "model": "gpt-5",\n    "explanation": "Research and synthesis with tools requires reasoning depth."\n  }\n  ```\n\n- **Summarize this email draft and make it more formal.**\n  ```json\n  {\n    "model": "gpt-5-chat-latest",\n    "explanation": "Polishing text only; no tools needed."\n  }\n  ```\n\n- **Summarize this uploaded PDF into bullet points.**\n  ```json\n  {\n    "model": "gpt-5",\n    "explanation": "Document parsing may require tools; complex enough for gpt-5."\n  }\n  ```\n\n- **Translate this paragraph into Spanish.**\n  ```json\n  {\n    "model": "gpt-5-chat-latest",\n    "explanation": "Simple translation; tools not required."\n  }\n  ```\n\n- **List my upcoming meetings tomorrow.**\n  ```json\n  {\n    "model": "gpt-5-mini",\n    "explanation": "Calendar tool lookup is simple; mini is efficient."\n  }\n  ```',
        "input": responses_body.input,
        "prompt_cache_key": "openai_responses_gpt5-router",
        "text": {
            "format": {
                "type": "json_schema",
                "name": "gpt5_router",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "enum": ["gpt-5-chat-latest", "gpt-5", "gpt-5-mini"],
                        },
                        "reasoning_effort": {
                            "type": "string",
                            "enum": ["minimal", "low", "medium", "high"],
                        },
                        "explanation": {
                            "type": "string",
                            "minLength": 3,
                            "maxLength": 500,
                        },
                    },
                    "required": ["model", "explanation", "reasoning_effort"],
                    "additionalProperties": False,
                },
                "verbosity": "medium",
            },
        },
    }

    try:
        response = await client.request(
            router_body,
            api_key=valves.API_KEY,
            base_url=valves.BASE_URL,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("GPT-5 router request failed: %s", exc)
        return responses_body

    try:
        text = next(
            (
                block["text"]
                for output in reversed(response["output"])
                if output["type"] == "message"
                for block in output["content"]
                if block["type"] == "output_text"
            ),
            "",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Router response missing expected fields: %s; payload keys=%s",
            exc,
            list(response.keys()),
        )
        return responses_body

    try:
        router_json: dict[str, Any] = json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        router_json = (
            json.loads(text[start : end + 1]) if start != -1 and end != -1 and end > start else {}
        )

    if router_json:
        model_choice = router_json.get("model")
        if isinstance(model_choice, str):
            responses_body.model = model_choice
        if supports("reasoning", responses_body.model):
            reasoning = dict(responses_body.reasoning or {})
            effort = router_json.get("reasoning_effort")
            if isinstance(effort, str):
                reasoning["effort"] = effort
            responses_body.reasoning = reasoning
        responses_body.model_router_result = router_json

    return responses_body
