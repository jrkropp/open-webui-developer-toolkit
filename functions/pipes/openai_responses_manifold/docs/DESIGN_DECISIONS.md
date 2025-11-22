# Design Documentation

## What is this document?

This is a design record that captures the **why** behind a significant architecture decision in the OpenAI Responses manifold. It is not a how-to guide and does not explain implementation details or usage. The goal is to document context, decision, alternatives, trade-offs, and acceptance criteria so future contributors understand the rationale.

How this document is structured:

* **Questions** frame the decision and its context.
* **Answers** describe the intent and rationale, not implementation steps.
* **Scope** is limited to design motivations and consequences.

---
# Design Decisions

## How should upstream filters add tools?
Upstream filters sometimes need to add or override tools before a request is sent to the provider. The challenge is that the canonical `body["tools"]` field is **rebuilt by Open WebUI when native function/tool calling is enabled**. Any filter that mutates this field directly risks losing its changes.

The decision: introduce a dedicated field, `extra_tools`, to give filters a **stable, reliable place to inject OpenAI-compatible tool specs**. The manifold merges this field into the final tool set at the last possible moment before sending the request.


### How are tools merged inside the manifold?

The manifold performs a **single merge step** just before sending the request to the provider. Tools are collected in this priority order:

1. **Open WebUI registry** (`__tools__`)
2. **Valve-generated tools** (e.g., web search, remote MCP)
3. **Filter-provided tools** (`extra_tools`)

Later sources override earlier ones. After merging, `extra_tools` is **stripped** from the outbound body so it never reaches the provider.

### How are conflicts resolved?

Tools are deduplicated by identity:

* **Function tools**: (`"function"`, `name`)
* **Non-function tools**: (`type`, `None`)

If the same identity appears multiple times, the later source wins. This allows filters to deliberately override registry or valve tools when needed.

### What happens if `extra_tools` contains invalid schemas?

The manifold does not perform deep validation. `extra_tools` is passed through as provided. Invalid entries may cause provider errors, but this is considered acceptable because the field is intended for use by trusted filters. Only minimal shape checks are applied.

### Example: Using `extra_tools`

**1) Upstream filter appends to the body**

```json
{
  "model": "openai_responses.gpt-5",
  "input": "What is 2+2?",
  "extra_tools": [
    {
      "type": "function",
      "name": "my_custom_tool",
      "description": "A filter-injected tool.",
      "parameters": {
        "type": "object",
        "properties": { "x": { "type": "integer" } },
        "required": ["x"]
      }
    }
  ]
}
```

**2) Outbound request sent to OpenAI**

```json
{
  "model": "gpt-5",
  "input": [
    { "role": "user", "content": [ { "type": "input_text", "text": "What is 2+2?" } ] }
  ],
  "tools": [
    {
      "type": "function",
      "name": "my_custom_tool",
      "description": "A filter-injected tool.",
      "parameters": {
        "type": "object",
        "additionalProperties": false,
        "properties": { "x": { "type": "integer" } },
        "required": ["x"]
      },
      "strict": true
    }
  ]
  // Note: extra_tools is removed before sending to OpenAI.
}
```

> **Idea:** Filters add OpenAI-compatible tools under `extra_tools`. The manifold picks them up and includes them in the final `tools` array, then **strips `extra_tools`** before sending the request to OpenAI.

---