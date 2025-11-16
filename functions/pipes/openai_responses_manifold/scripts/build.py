#!/usr/bin/env python
"""Bundle the src/openai_responses_manifold package back into a single openai_responses_manifold.py file."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any
import tomllib

SCRIPTS_DIR = Path(__file__).resolve().parent
PIPE_ROOT = SCRIPTS_DIR.parent
SRC_DIR = PIPE_ROOT / "src"
PACKAGE_NAME = "openai_responses_manifold"
PACKAGE_DIR = SRC_DIR / PACKAGE_NAME
OUTPUT_FILE = PIPE_ROOT / "openai_responses_manifold.py"
PYPROJECT_FILE = PIPE_ROOT / "pyproject.toml"

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


def _load_pyproject() -> dict[str, Any]:
    with PYPROJECT_FILE.open("rb") as handle:
        return tomllib.load(handle)


def _license_text(project: dict[str, Any]) -> str:
    license_value = project.get("license")
    if isinstance(license_value, dict):
        return license_value.get("text") or license_value.get("file") or ""
    if isinstance(license_value, str):
        return license_value
    return ""


def _first_author_name(project: dict[str, Any]) -> str:
    authors = project.get("authors") or []
    for entry in authors:
        if isinstance(entry, dict) and entry.get("name"):
            return entry["name"]
        if isinstance(entry, str) and entry.strip():
            return entry.strip()
    return ""


def _render_manifest_docstring() -> str:
    data = _load_pyproject()
    project = data.get("project") or {}
    custom_keys = {
        "open_webui_id": project.get("open_webui_id"),
        "open_webui_author_url": project.get("open_webui_author_url"),
        "open_webui_git_url": project.get("open_webui_git_url"),
        "open_webui_required_version": project.get("open_webui_required_version"),
    }
    missing = [key for key, value in custom_keys.items() if not value]
    if not _first_author_name(project):
        missing.append("authors[0].name")
    if missing:
        raise RuntimeError(
            f"Missing manifest metadata in pyproject.toml: {', '.join(sorted(missing))}"
        )

    requirements_list = project.get("dependencies") or []
    requirements = ", ".join(requirements_list)

    author_name = _first_author_name(project)

    fields: list[tuple[str, str]] = [
        ("title", project.get("description") or project.get("name") or ""),
        ("id", custom_keys["open_webui_id"]),
        ("author", author_name),
        ("author_url", custom_keys["open_webui_author_url"]),
        ("git_url", custom_keys["open_webui_git_url"]),
        ("description", project.get("description") or ""),
        ("required_open_webui_version", custom_keys["open_webui_required_version"]),
        ("requirements", requirements),
        ("version", project.get("version", "")),
        ("license", _license_text(project)),
    ]

    doc_lines = [f"{key}: {value}" for key, value in fields if value]

    notes = (project.get("open_webui_notes") or "").strip()
    if notes:
        doc_lines.extend(["", notes])

    return "\n".join(doc_lines)


def extract_manifest_block() -> str:
    manifest = _render_manifest_docstring()
    if not manifest.strip():
        raise RuntimeError("Generated manifest docstring is empty")
    return manifest.strip()


def clean_module_source(module_path: Path) -> str:
    source = module_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    source = _strip_future_imports(source)
    source, alias_lines = _strip_relative_imports(source)
    source = _collapse_blank_lines(source).strip()
    if alias_lines:
        source = _inject_alias_lines(source, alias_lines)
        source = _collapse_blank_lines(source).strip()
    return source


def _strip_future_imports(source: str) -> str:
    """Remove ``from __future__`` imports plus the blank line that followed them."""

    lines = source.splitlines()
    cleaned: list[str] = []
    drop_next_blank = False

    for line in lines:
        if FUTURE_IMPORT_RE.match(line):
            drop_next_blank = True
            continue

        if drop_next_blank:
            drop_next_blank = False
            if line.strip():
                cleaned.append(line)
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


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


def _collapse_blank_lines(source: str, *, max_consecutive: int = 2) -> str:
    """Ensure we never emit more than ``max_consecutive`` empty lines in a row."""

    if max_consecutive < 1:
        return source

    lines = source.splitlines()
    collapsed: list[str] = []
    blank_count = 0

    for line in lines:
        if line.strip():
            blank_count = 0
            collapsed.append(line)
            continue

        blank_count += 1
        if blank_count <= max_consecutive:
            collapsed.append("")

    return "\n".join(collapsed)


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
    manifest_text = extract_manifest_block()
    manifest_block = f'"""\n{manifest_text}\n"""'
    sections: list[str] = [manifest_block, "", "from __future__ import annotations", ""]

    for module in MODULE_ORDER:
        module_path = PACKAGE_DIR / module
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
    parser = argparse.ArgumentParser(description="Bundle src/openai_responses_manifold/ into openai_responses_manifold.py")
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
