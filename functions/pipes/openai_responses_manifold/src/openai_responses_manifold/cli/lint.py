from __future__ import annotations

import argparse
import sys

from .utils import PIPE_ROOT, run_command


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("lint", help="Run Ruff checks (optionally with fixes).")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply Ruff autofixes (equivalent to `ruff check --fix`).",
    )
    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    command = [sys.executable, "-m", "ruff", "check"]
    if args.fix:
        command.append("--fix")
    command.extend(["src", "tests"])
    return run_command(command, cwd=PIPE_ROOT)
