# External Resources

This folder collects all Open WebUI reference material.

- `open-webui/` is a **git submodule** pointing to the upstream [Open WebUI](https://github.com/open-webui/open-webui) repository. Treat it as read-only — do **not** edit files inside this directory. Run `git submodule update --init` if it's empty.
- `*_GUIDE.md` files summarise helper modules from `backend/open_webui/utils/`.
  If you inspect the source under `open-webui/` and notice new behaviour, update the corresponding guide.

| File | Purpose |
|------|---------|
|[ACCESS_CONTROL_GUIDE.md](ACCESS_CONTROL_GUIDE.md)|Group based permission checks used across the API.|
|[AUTH_GUIDE.md](AUTH_GUIDE.md)|Password hashing, JWT handling and license utilities.|
|[CHAT_GUIDE.md](CHAT_GUIDE.md)|Routes chat completions and streams the result.|
|[PAYLOAD_GUIDE.md](PAYLOAD_GUIDE.md)|Normalises request bodies and converts payloads.|
|[TOOLS_GUIDE.md](TOOLS_GUIDE.md)|Discovers tool modules and builds JSON specs.|
|[TASK_GUIDE.md](TASK_GUIDE.md)|Creates prompts for background tasks and selects models.|
|[MODELS_GUIDE.md](MODELS_GUIDE.md)|Merges built-in, Ollama and user models.|
|[FILTER_GUIDE.md](FILTER_GUIDE.md)|Pipeline system for mutating requests/responses.|
|[PLUGIN_GUIDE.md](PLUGIN_GUIDE.md)|Loads extension modules from the database.|
|[MIDDLEWARE_GUIDE.md](MIDDLEWARE_GUIDE.md)|Orchestrates the chat pipeline – payload processing, model invocation and response streaming.|
|[OAUTH_GUIDE.md](OAUTH_GUIDE.md)|Implements OAuth provider login and group synchronisation.|
|[MISC_GUIDE.md](MISC_GUIDE.md)|Assorted helpers such as message utilities.|
|[REDIS_GUIDE.md](REDIS_GUIDE.md)|Connection helpers and convenience classes backed by Redis.|
|[CODE_INTERPRETER_GUIDE.md](CODE_INTERPRETER_GUIDE.md)|Executes Python code in a Jupyter kernel for the code interpreter feature.|

