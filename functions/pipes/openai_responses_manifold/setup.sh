#!/usr/bin/env bash
set -euo pipefail

# Bootstrap dev environment for OpenAI Responses Manifold.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

"$PYTHON_BIN" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install -U pip setuptools wheel
python -m pip install -e '.[dev]'

# Quick smoke check of the CLI.
orm --help
