from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .utils import PIPE_ROOT, run_command


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("test", help="Run the pytest suite.")
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Optional arguments forwarded to pytest (prefix with --).",
    )
    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    forwarded: Sequence[str] = args.pytest_args
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]

    command = [sys.executable, "-m", "pytest", *forwarded]
    return run_command(command, cwd=PIPE_ROOT)
