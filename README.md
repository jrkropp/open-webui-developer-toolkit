# Open-WebUI Developer Toolkit
[![Open WebUI](https://img.shields.io/badge/Open%20WebUI-Repository-blue?logo=github)](https://github.com/open-webui/open-webui)
[![License MIT](https://img.shields.io/github/license/jrkropp/open-webui-developer-toolkit?color=blue)](LICENSE)

**Open-WebUI Developer Toolkit** is a collection of **pipes**, **filters**, and **tools** that extend [Open WebUI](https://github.com/open-webui/open-webui). This toolkit adds extra capabilities to the Open WebUI platform – including example pipes/filters/tools and supporting documentation.

*Open WebUI* is an open-source, self-hosted AI interface. The extensions in this toolkit assume you have a working Open WebUI installation (Python 3.11+). The target audience is technical users and developers familiar with Python and OpenAI’s APIs who want to enhance Open WebUI with custom pipeline components.

## Repository Layout

This repository is organized as follows:

- **`functions/pipes/`** – Self‑contained pipeline components (“pipes”) that transform or generate chat messages (e.g. by calling external APIs or injecting content).
- **`functions/filters/`** – Reusable filters that run before or after pipes to inspect or modify messages (e.g. toggling behavior or sanitizing inputs/outputs).
- **`tools/`** – Standalone tools (Open WebUI “Tools”) that provide new abilities to the assistant (in the form of tool plugins available via the Open WebUI Tools interface).
- **`docs/`** – Internal notes and documentation on Open WebUI internals (useful for advanced developers writing custom filters, pipes, or tools).

Each subdirectory contains its own README with details about the contents. For example, the `functions/` directory has guides on how pipes and filters work in Open WebUI, and each extension subfolder documents that particular extension.

## Available Extensions

The following extensions are currently included in the Open-WebUI Developer Toolkit:

| Name                     | Description                                                            | Links (Branch)                               |
| ------------------------ | ---------------------------------------------------------------------- | ------------------------------------------- |
| **Input Inspector**      | Debugging pipe that displays pipeline input arguments as citation blocks (useful for seeing raw `body`, request metadata, user info, etc.). | [Stable](https://github.com/jrkropp/open-webui-developer-toolkit/tree/main/functions/pipes/input_inspector) _(main)_<br>[Preview](https://github.com/jrkropp/open-webui-developer-toolkit/tree/alpha-preview/functions/pipes/input_inspector) _(alpha-preview)_ |
| **OpenAI Responses Manifold** | Pipe that integrates OpenAI’s **Responses API** into Open WebUI, enabling advanced OpenAI features such as native function calling, web search tools, visible reasoning traces, and more. Now fully compatible with the Open WebUI **Notes** feature. | [Stable](https://github.com/jrkropp/open-webui-developer-toolkit/tree/main/functions/pipes/openai_responses_manifold) _(main)_<br>[Preview](https://github.com/jrkropp/open-webui-developer-toolkit/tree/alpha-preview/functions/pipes/openai_responses_manifold) _(alpha-preview)_ |
| **OpenAI Prompt Object Filter** | Filter that removes system messages when a prompt object is provided, passing the `prompt` through unchanged. | [Stable](https://github.com/jrkropp/open-webui-developer-toolkit/tree/main/functions/pipes/openai_prompt_object_filter) _(main)_<br>[Preview](https://github.com/jrkropp/open-webui-developer-toolkit/tree/alpha-preview/functions/pipes/openai_prompt_object_filter) _(alpha-preview)_ |
| **Reason Toggle Filter** | Filter that temporarily routes a request to an alternate model based on a “reasoning effort” setting. Allows dynamic switching to a more powerful model for high reasoning demands. | [Stable](https://github.com/jrkropp/open-webui-developer-toolkit/tree/main/functions/filters/reason_toggle_filter) _(main)_<br>[Preview](https://github.com/jrkropp/open-webui-developer-toolkit/tree/alpha-preview/functions/filters/reason_toggle_filter) _(alpha-preview)_ |

> _More extensions are planned._ We encourage the community to suggest or contribute new pipes, filters, and tools. Each extension in the table above has documentation on usage and any configuration needed.

## Branching Model

This project uses a **three-branch model** to manage stability and new development:

1. **`main`** – **Stable**: Production-ready code. This is the default branch with the latest stable release of all extensions.
2. **`alpha-preview`** – **Release Candidate**: Next release in testing. Extensions here include the latest features that have passed initial development and are in a 2–3 week evaluation period before merging to main.
3. **`development`** – **Active Development**: Unstable and in-progress changes. All new contributions and experiments start here. This branch may be broken at times and is not intended for end users.

The typical workflow is:  
```

development (continuous changes) → alpha-preview (testing/QA) → main (stable release)

````

When using the toolkit, you can choose the branch that suits your needs. Most users should stick to **main** for stability. If you want to test the latest features (with a slight risk), use **alpha-preview**.

**Note:** The `external/open-webui/` directory is a **git submodule** pointing to the upstream [Open WebUI](https://github.com/open-webui/open-webui) repository. It’s included as a read-only reference to assist with testing compatibility, so you don’t have to separately clone the main Open WebUI project. When writing new extensions, you can refer to Open WebUI internals (APIs, data models, etc.) via this local copy. To populate it, clone with `git clone --recurse-submodules`, or run `git submodule update --init` in an existing checkout.

## Development Setup

The project uses a standard `pyproject.toml`. With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
git submodule update --init   # tests import from external/open-webui/backend
uv sync --extra dev           # creates .venv and installs runtime + dev dependencies
uv run pytest                 # run the test suite (or .venv/bin/pytest)
```

Any tool that understands `pyproject.toml` works too, e.g. `pip install -e ".[dev]"` in a Python 3.11+ virtualenv.

## Contributing

Contributions are welcome! If you have an idea for a new pipe, filter, tool, or an improvement to the existing code, please feel free to get involved:

* **Bug Reports & Feature Requests:** Use the GitHub Issues to report problems or suggest new features. Providing a clear description and steps to reproduce (for bugs) helps a lot.
* **Pull Requests:** If you want to contribute code, you can fork the repository and open a PR.
* **Discussion:** For significant changes or design questions, you may start a discussion or reach out to maintainers via GitHub Discussions.

By contributing to this project, you agree that your contributions will be licensed under the same MIT License that covers the project.

## License

This project is licensed under the **MIT License**. You are free to use, modify, and distribute this software. See the [LICENSE](LICENSE) file for the full license text.

---

*Happy hacking! 🚀 If you find this toolkit useful or build something interesting with it, let us know. We’re excited to see how the community extends Open WebUI.*
*If you encounter any issues, please check the documentation in the `docs/` folder or open an issue for assistance.*
