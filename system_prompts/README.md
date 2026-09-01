# System Prompts

Reference system prompts for models deployed through this toolkit (e.g. via the
[OpenAI Responses Manifold](../functions/pipes/openai_responses_manifold/AGENTS.md)).
They mirror ChatGPT-style prompt conventions, adapted for Open WebUI deployments.

| File | Purpose |
|---|---|
| `gpt-5-thinking.md` | Chat-optimized prompt for GPT-5 reasoning models: personality v2, no opt-in closers, markdown formatting rules, `web` tool guidance. |
| `gpt-4.1.md` | GPT-4.1 prompt: adaptive tone, aggressive web-browsing policy, Yap verbosity score, `web` tool command reference with citation rules. |

Notes:
- Placeholders like `{{CURRENT_DATE}}` / `{{CURRENT_WEEKDAY}}` are expanded by Open WebUI.
- Blanks (`____`) are intentional — fill in your organization/deployment name.
- Keep prompts model-specific; when adding one, name the file after the model family.
