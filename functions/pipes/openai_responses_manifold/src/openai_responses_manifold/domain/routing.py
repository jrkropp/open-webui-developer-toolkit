"""Helper model routing for auto variants."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai_responses_manifold.adapters.openai.client import OpenAIResponsesClient
from openai_responses_manifold.adapters.openai.requests import ResponseCreateParams
from openai_responses_manifold.core.logging import get_logger, truncate_for_log
from openai_responses_manifold.domain.events import RuntimeEvents

logger = get_logger(__name__)


async def route_auto_model(
    client: OpenAIResponsesClient,
    *,
    router_model: str,
    responses_body: ResponseCreateParams,
    valves: Any,
    tools: list[dict[str, Any]],
    events: RuntimeEvents | None = None,
) -> ResponseCreateParams:
    """
    Use a small helper model to choose the final GPT-5 variant and reasoning effort.

    The helper request mirrors the structure described in the Developer Guide v2.
    """

    tool_context = _summarize_tools(tools)
    instructions = _ROUTER_PROMPT
    if tool_context:
        instructions = f"{_ROUTER_PROMPT}\n\n# Tool Context\n{tool_context}"

    router_body = {
        "model": router_model,
        "reasoning": {"effort": "minimal"},
        "instructions": instructions,
        "input": responses_body.input,
        "prompt_cache_key": "openai_responses_gpt5-router",
        "text": {
            "format": {
                "type": "json_schema",
                "name": "gpt5_router",
                "strict": True,
                "schema": _ROUTER_SCHEMA,
                "verbosity": "medium",
            },
        },
    }

    try:
        response = await client.create(
            router_body,
            api_key=valves.API_KEY,
            base_url=valves.BASE_URL,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Model router request failed: %s", exc)
        return responses_body

    text = _extract_router_text(response)
    if not text:
        return responses_body

    try:
        router_json: dict[str, Any] = json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        router_json = (
            json.loads(text[start : end + 1]) if start != -1 and end != -1 and end > start else {}
        )

    if not router_json:
        return responses_body

    model_choice = router_json.get("model")
    if isinstance(model_choice, str):
        responses_body.model = model_choice
    effort = router_json.get("reasoning_effort")
    if isinstance(effort, str):
        current_reasoning = responses_body.reasoning if isinstance(responses_body.reasoning, dict) else {}
        responses_body.reasoning = {**current_reasoning, "effort": effort}

    responses_body.model_router_result = router_json
    explanation = router_json.get("explanation")
    if isinstance(explanation, str) and events:
        await events.status(
            f"Routing to {router_json.get('model')} (effort: {router_json.get('reasoning_effort')})\nExplanation: {explanation}"
        )
    return responses_body


def _extract_router_text(response: dict[str, Any]) -> str:
    try:
        return next(
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
        payload_preview, truncated = truncate_for_log(
            json.dumps(response, ensure_ascii=False), limit=800
        )
        logger.warning(
            "Router response missing expected fields: %s payload_keys=%s truncated=%s payload=%s",
            exc,
            list(response.keys()),
            truncated,
            payload_preview,
        )
        return ""


_ROUTER_SCHEMA = {
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
}

_ROUTER_PROMPT = """# Role and Objective
Serve as a **routing helper** for selecting the most appropriate GPT-5 model for user messages, evaluating tool necessity and task complexity.

---

# Instructions
- If a message may require the use of **any available tool**, select a model with **function calling** capabilities. If **web search** is required, you may only choose **low, medium or high** reasoning, not minimal.
- When tools are not necessary, favor the **fastest** or **most capable** model according to the complexity of the request.

---

# Available Models and Capabilities
## Models

- **gpt-5-chat-latest**
  - Fast, general-purpose, and creative.
  - Best for writing, drafting, and chat-based interactions.
  - ⚠️ Does **not** support tool calling—select only when tools are not required.

- **gpt-5-mini**
  - Lightweight, supports tool usage, and is rapidly responsive.
  - Suited for **simple tasks that may use tools** but don't demand extensive reasoning.
  - ✅ Function calling supported—offers a strong balance between speed and utility.

- **gpt-5**
  - Strong at reasoning and complex, multi-step analysis.
  - Designed for **complex or deeply analytical tasks**.
  - ✅ Supports function calling and advanced operations—choose for tool-reliant or high-complexity reasoning needs.

---

# Routing Checklist
- Assess whether tool integration could improve the response.
- Evaluate how much reasoning or problem-solving is required.
- Match model to requirements:
  - No tool usage required → use `gpt-5-chat-latest`
  - Tools required, simple task → use `gpt-5-mini`
  - Tools required, complex task → use `gpt-5`
- When in doubt, prioritize a tool-capable model (prefer `gpt-5`).
- Ask for more information if requirements are ambiguous.

---

# Output Format
Respond only with a JSON object containing your model selection and a concise explanation. If the requirements are unclear, include an appropriate error message in the JSON response.

---

# Examples
- **What's the weather in Vancouver right now?**
  ```json
  {
    "model": "gpt-5-mini",
    "explanation": "Quick tool lookup; simple enough for a fast model."
  }
  ```

- **Compare the newest M3 laptops and cite sources.**
  ```json
  {
    "model": "gpt-5",
    "explanation": "Research and synthesis with tools requires reasoning depth."
  }
  ```

- **Summarize this email draft and make it more formal.**
  ```json
  {
    "model": "gpt-5-chat-latest",
    "explanation": "Polishing text only; no tools needed."
  }
  ```

- **Summarize this uploaded PDF into bullet points.**
  ```json
  {
    "model": "gpt-5",
    "explanation": "Document parsing may require tools; complex enough for gpt-5."
  }
  ```

- **Translate this paragraph into Spanish.**
  ```json
  {
    "model": "gpt-5-chat-latest",
    "explanation": "Simple translation; tools not required."
  }
  ```

- **List my upcoming meetings tomorrow.**
  ```json
  {
    "model": "gpt-5-mini",
    "explanation": "Calendar tool lookup is simple; mini is efficient."
  }
  ```
"""

def _summarize_tools(tools: list[dict[str, Any]]) -> str:
    if not tools:
        return "No tools are provided for this request."

    labels: list[str] = []
    for tool in tools:
        tool_type = tool.get("type")
        if tool_type == "function":
            name = tool.get("name")
            if isinstance(name, str):
                labels.append(f"function:{name}")
        elif isinstance(tool_type, str):
            labels.append(tool_type)

    deduped = sorted({label for label in labels if label})
    joined = ", ".join(deduped) if deduped else "unspecified tools"
    return f"Tools available: {joined}. Prefer a tool-capable model when tools may be used."

__all__ = ["route_auto_model"]
