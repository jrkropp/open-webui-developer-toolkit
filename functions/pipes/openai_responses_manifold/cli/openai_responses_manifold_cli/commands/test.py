from __future__ import annotations

import sys

import typer

from ..utils import PIPE_ROOT, run_command


def register(app: typer.Typer) -> None:
    @app.command(
        "test",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
        help="Run the pytest suite (extra args are forwarded).",
    )
    def _test(ctx: typer.Context) -> None:
        forwarded = list(ctx.args)
        command = [sys.executable, "-m", "pytest", *forwarded]
        raise typer.Exit(run_command(command, cwd=PIPE_ROOT))
