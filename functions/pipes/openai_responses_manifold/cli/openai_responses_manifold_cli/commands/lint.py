from __future__ import annotations

import sys

import typer

from ..utils import PIPE_ROOT, run_command


def register(app: typer.Typer) -> None:
    @app.command("lint", help="Run Ruff checks (optionally with fixes).")
    def _lint(
        fix: bool = typer.Option(
            False,
            "--fix",
            help="Apply Ruff autofixes (equivalent to `ruff check --fix`).",
        ),
    ) -> None:
        command = [sys.executable, "-m", "ruff", "check"]
        if fix:
            command.append("--fix")
        command.extend(["src", "tests", "cli"])
        raise typer.Exit(run_command(command, cwd=PIPE_ROOT))
