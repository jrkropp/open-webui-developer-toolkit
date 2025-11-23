from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import build, lint, test


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openai-responses-manifold",
        description="Developer CLI for the OpenAI Responses Manifold pipe.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for module in (build, test, lint):
        module.register(subparsers)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.error("No command provided")
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
