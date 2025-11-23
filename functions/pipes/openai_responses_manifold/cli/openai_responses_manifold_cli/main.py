from __future__ import annotations

import typer

from .commands import build, lint, test

app = typer.Typer(
    name="openai-responses-manifold",
    help="Developer CLI for the OpenAI Responses Manifold pipe.",
    add_completion=False,
)

for module in (build, test, lint):
    module.register(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
