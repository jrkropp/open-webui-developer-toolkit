#!/usr/bin/env python
"""Bundle the src/ package back into a single openai_responses_manifold.py file."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PIPE_ROOT = SCRIPTS_DIR.parent
SRC_DIR = PIPE_ROOT / "src"
PACKAGE_DIR = SRC_DIR
OUTPUT_FILE = PIPE_ROOT / "openai_responses_manifold.py"

MODULE_ORDER = [
    "core/capabilities.py",
    "pipe.py",
    "core/markers.py",
    "core/session_logger.py",
    "core/utils.py",
    "core/models.py",
    "infra/persistence.py",
    "infra/client.py",
    "features/tools.py",
    "features/router.py",
]

RELATIVE_IMPORT_RE = re.compile(r"^\s*from\s+\.+\w*")
FUTURE_IMPORT_RE = re.compile(r"^from\s+__future__\s+import\s+.*$", re.MULTILINE)


def log(message: str) -> None:
    print(f"[build] {message}")


def run_pytest() -> int:
    log("Running pytest…")
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests"], cwd=PIPE_ROOT)
    if proc.returncode != 0:
        log("Tests failed; aborting build.")
    return proc.returncode


def extract_manifest_block() -> str:
    metadata_path = SRC_DIR / "metadata.py"
    metadata_src = metadata_path.read_text(encoding="utf-8")
    match = re.search(r'MANIFEST\s*=\s*(?P<doc>"""[\s\S]*?""")', metadata_src)
    if not match:
        raise RuntimeError("Unable to locate MANIFEST block in src/metadata.py")
    return match.group("doc").strip()


def clean_module_source(module_path: Path) -> str:
    source = module_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    source = FUTURE_IMPORT_RE.sub("", source)
    source, alias_lines = _strip_relative_imports(source)
    source = source.strip()
    if alias_lines:
        source = _inject_alias_lines(source, alias_lines)
    return source


def _strip_relative_imports(source: str) -> tuple[str, list[str]]:
    lines = source.splitlines()
    cleaned: list[str] = []
    alias_lines: list[str] = []
    skipping = False
    buffer: list[str] = []
    paren_depth = 0

    for line in lines:
        if skipping:
            buffer.append(line)
            paren_depth += line.count("(") - line.count(")")
            if paren_depth <= 0:
                alias_lines.extend(_alias_lines_for_import("\n".join(buffer)))
                buffer = []
                skipping = False
            continue

        if RELATIVE_IMPORT_RE.match(line):
            buffer = [line]
            paren_depth = line.count("(") - line.count(")")
            if paren_depth <= 0:
                alias_lines.extend(_alias_lines_for_import("\n".join(buffer)))
                buffer = []
            else:
                skipping = True
            continue

        cleaned.append(line)

    return "\n".join(cleaned), alias_lines


def _alias_lines_for_import(statement: str) -> list[str]:
    import ast

    try:
        tree = ast.parse(statement)
    except SyntaxError:
        return []

    aliases: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level <= 0:
            continue
        for alias in node.names:
            if alias.asname:
                aliases.append(f"{alias.asname} = {alias.name.rsplit('.', 1)[-1]}")
    return aliases


def _inject_alias_lines(source: str, alias_lines: list[str]) -> str:
    if not alias_lines:
        return source
    lines = source.splitlines()
    insert_idx = 0
    while insert_idx < len(lines) and not lines[insert_idx].strip():
        insert_idx += 1
    if insert_idx < len(lines) and lines[insert_idx].lstrip().startswith(('"""', "'''")):
        quote = lines[insert_idx].lstrip()[:3]
        idx = insert_idx
        line = lines[idx].lstrip()
        if line.count(quote) == 1:
            idx += 1
            while idx < len(lines):
                if quote in lines[idx]:
                    idx += 1
                    break
                idx += 1
        else:
            idx += 1
        insert_idx = idx
    insertion = ["# alias imports removed during bundling", *alias_lines, ""]
    lines[insert_idx:insert_idx] = insertion
    return "\n".join(lines)


def run_build() -> int:
    log("Bundling openai_responses_manifold.py…")
    manifest_block = extract_manifest_block()
    sections: list[str] = [manifest_block, "", "from __future__ import annotations", ""]

    for module in MODULE_ORDER:
        module_path = SRC_DIR / module
        if not module_path.exists():
            raise RuntimeError(f"Module not found: {module}")
        cleaned = clean_module_source(module_path)
        sections.append(f"# === {module} ===")
        sections.append(cleaned)
        sections.append("")

    OUTPUT_FILE.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    log(f"Wrote {OUTPUT_FILE.relative_to(PIPE_ROOT)}")
    return 0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bundle src/ into openai_responses_manifold.py")
    parser.add_argument(
        "--skip-tests", action="store_true", help="Skip running pytest before building."
    )
    parser.add_argument("--tests-only", action="store_true", help="Only run pytest (no build).")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.tests_only:
        return run_pytest()
    if not args.skip_tests:
        status = run_pytest()
        if status != 0:
            return status
    return run_build()


if __name__ == "__main__":
    raise SystemExit(main())
