from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Sequence

PACKAGE_NAME = "openai_responses_manifold"
PIPE_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PIPE_ROOT / "src"
PACKAGE_DIR = SRC_DIR / PACKAGE_NAME
OUTPUT_FILE = PIPE_ROOT / "openai_responses_manifold.py"
PYPROJECT_FILE = PIPE_ROOT / "pyproject.toml"


def format_command(command: Sequence[str]) -> str:
    """Return a shell-escaped string version of the command."""
    return " ".join(shlex.quote(part) for part in command)


def run_command(command: Sequence[str], *, cwd: Path | None = None) -> int:
    """Run a subprocess, echoing the command first, and return its exit code."""
    print(f"[cli] {format_command(command)}")
    return subprocess.run(command, cwd=cwd).returncode
