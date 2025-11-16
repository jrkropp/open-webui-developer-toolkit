# Agents Guide – OpenAI Responses Manifold

Keep this note open whenever you work in `functions/pipes/openai_responses_manifold/`.

## Purpose
- Provides the OpenAI Responses API integration for Open WebUI.
- The checked-in `openai_responses_manifold.py` is generated; only edit modules under `src/`.

## Folder Map
```
functions/pipes/openai_responses_manifold/
├─ AGENTS.md                # This guide
├─ pyproject.toml           # packaging + pytest/ruff config for this pipe
├─ Makefile                 # dev shortcuts (install/test/lint/format/build/dist/clean)
├─ scripts/
│  └─ build.py              # pytest + bundler entrypoint
├─ src/
│  ├─ core/                 # edit code here (capabilities, models, utilities)
│  ├─ features/
│  ├─ infra/
│  ├─ pipe.py
│  └─ metadata.py           # declares requirements for Open WebUI
├─ tests/                   # pytest suite
└─ openai_responses_manifold.py   # generated artifact (never hand-edit)
```

## Key Commands
- `make install` — editable install with runtime deps only.
- `make install-dev` — editable install including the `dev` extra (pytest, ruff, etc.).
- `make test` — run the pytest suite.
- `make lint` — run Ruff checks over `src/` and `tests/`.
- `make lint-fix` — run Ruff checks with autofix over `src/` and `tests/`.
- `make format` — apply Ruff formatting fixes.
- `make build` — run pytest, then regenerate the monolithic `openai_responses_manifold.py`.
- `python scripts/build.py --tests-only` — run pytest without rebuilding the artifact.
- `python scripts/build.py --skip-tests` — rebuild without running pytest.

## Workflow
1. Create/activate a local venv (`python -m venv .venv && source .venv/bin/activate` on Unix, `.\.venv\Scripts\activate` on Windows).
2. Install the pipe plus dev tooling: `python -m pip install -e .[dev]` from the pipe root.
3. Install dev tooling and enable hooks (`python -m pip install pre-commit`, `pre-commit install`).
4. Make changes inside `src/` (never edit the generated file directly).
5. Run `make test` until the suite passes.
6. Regenerate the bundled artifact with `make build` (run `python scripts/build.py --skip-tests` only if pytest already passed).
7. Review `git status` to confirm both the `src/` edits and the regenerated artifact are staged.

## Notes
- If you add a dependency, declare it in `src/metadata.py` under `requirements`.
- `tests/test_dependencies_sync.py` fails if `pyproject.toml` and `src/metadata.py` disagree on dependencies—update both together.
- Update this guide whenever the workflow or commands change.
- Pre-commit hooks live at the repo root (`.pre-commit-config.yaml`) but are scoped to this directory, so feel free to enable them.
- Source modules now live directly under `src/`; always edit code there and rebuild the bundle via `make build`.
