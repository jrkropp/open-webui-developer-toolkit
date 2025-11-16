#!/usr/bin/env python
"""
build.py

Bundle the multi-module package under src/openai_responses_manifold/ into a
single openai_responses_manifold.py file suitable for use as an Open WebUI pipe.

Design goals:
- Keep development ergonomics: normal Python package with modules, imports, tests.
- Emit a monolithic file with:
  - A manifest docstring derived from pyproject.toml (for Open WebUI).
  - A human-readable file tree comment describing the logical layout.
    - Descriptions are pulled dynamically from each module's top-level docstring.
  - A single `from __future__ import annotations` at the top.
  - All internal imports stripped/commented, so the file acts as ONE module.
- Preserve a fixed, intentional section order to make the monolith easy to read.

Usage:
    python scripts/build.py             # run tests, then bundle
    python scripts/build.py --skip-tests
    python scripts/build.py --tests-only
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

import tomllib

# ---------------------------------------------------------------------------
# Paths and basic constants
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent
PIPE_ROOT = SCRIPTS_DIR.parent
SRC_DIR = PIPE_ROOT / "src"
PACKAGE_NAME = "openai_responses_manifold"
PACKAGE_DIR = SRC_DIR / PACKAGE_NAME
OUTPUT_FILE = PIPE_ROOT / "openai_responses_manifold.py"
PYPROJECT_FILE = PIPE_ROOT / "pyproject.toml"

# Logical order modules will appear in the monolith.
MODULE_ORDER: list[str] = [
    "model_catalog.py",
    "settings.py",
    "main.py",
    "engine.py",
    "core/api_models.py",
    "core/ids.py",
    "core/capabilities.py",
    "core/messages.py",
    "core/markers.py",
    "core/errors.py",
    "services/history.py",
    "services/tools.py",
    "services/routing.py",
    "infra/openwebui_store.py",
    "infra/openai_client.py",
    "utils/logging.py",
    "utils/events.py",
]

# Regex for stripping `from __future__ import ...` from individual modules.
FUTURE_IMPORT_RE = re.compile(r"^from\s+__future__\s+import\s+.*$", re.MULTILINE)

# Names considered "internal" to the package; imports from these are stripped.
INTERNAL_MODULES = {"model_catalog", "settings", "main", "engine"}
INTERNAL_PREFIXES = ("core", "services", "infra", "utils")
PACKAGE_PREFIX = f"{PACKAGE_NAME}."


# ---------------------------------------------------------------------------
# Utility logging
# ---------------------------------------------------------------------------

def log(message: str) -> None:
    """Simple build-time logger."""
    print(f"[build] {message}")


# ---------------------------------------------------------------------------
# pyproject.toml / manifest helpers
# ---------------------------------------------------------------------------

def _load_pyproject() -> dict[str, Any]:
    """Load pyproject.toml as a dict."""
    with PYPROJECT_FILE.open("rb") as handle:
        return tomllib.load(handle)


def _license_text(project: dict[str, Any]) -> str:
    """Extract license text/file from pyproject."""
    license_value = project.get("license")
    if isinstance(license_value, dict):
        return license_value.get("text") or license_value.get("file") or ""
    if isinstance(license_value, str):
        return license_value
    return ""


def _first_author_name(project: dict[str, Any]) -> str:
    """Return the first author name from pyproject, or an empty string."""
    authors = project.get("authors") or []
    for entry in authors:
        if isinstance(entry, dict) and entry.get("name"):
            return entry["name"]
        if isinstance(entry, str) and entry.strip():
            return entry.strip()
    return ""


def _render_manifest_docstring() -> str:
    """
    Build the manifest docstring for Open WebUI from pyproject.toml.

    Enforces the presence of required metadata. If anything is missing,
    raises a RuntimeError with a helpful message, rather than quietly
    emitting a broken manifest.
    """
    data = _load_pyproject()
    project = data.get("project") or {}
    tool_config = data.get("tool") or {}
    open_webui_metadata = (
        tool_config.get("open_webui_metadata")
        or project.get("open_webui_metadata")
        or {}
    )

    # Fields required for our Open WebUI manifest.
    custom_keys = {
        "open_webui_id": open_webui_metadata.get("open_webui_id"),
        "open_webui_author_url": open_webui_metadata.get("open_webui_author_url"),
        "open_webui_git_url": open_webui_metadata.get("open_webui_git_url"),
        "open_webui_required_version": open_webui_metadata.get(
            "open_webui_required_version"
        ),
    }

    missing: list[str] = [key for key, value in custom_keys.items() if not value]
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

    notes = (open_webui_metadata.get("open_webui_notes") or "").strip()
    if notes:
        doc_lines.extend(["", notes])

    return "\n".join(doc_lines)


def extract_manifest_block() -> str:
    """Render and validate the manifest block, returning a trimmed string."""
    manifest = _render_manifest_docstring()
    if not manifest.strip():
        raise RuntimeError("Generated manifest docstring is empty")
    return manifest.strip()


# ---------------------------------------------------------------------------
# Module docstrings → descriptions for file tree
# ---------------------------------------------------------------------------

def _get_module_docstring(rel_path: str) -> str:
    """
    Return the first line of the module-level docstring for the given module,
    or an empty string if none is found.

    rel_path is a path relative to PACKAGE_DIR, e.g. "core/api_models.py".
    """
    module_path = PACKAGE_DIR / rel_path
    if not module_path.exists():
        return ""

    try:
        source = module_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    doc = ast.get_docstring(tree)
    if not doc:
        return ""

    # Use the first line as a concise summary.
    first_line = doc.strip().splitlines()[0]
    return first_line.strip()


def _render_file_tree_comment() -> str:
    """
    Render a commented file tree describing how the monolith was built.

    This block appears directly under the manifest docstring in the
    generated openai_responses_manifold.py, and serves as a high-level
    guide for humans (and AI tools) reading the file.

    Descriptions are pulled dynamically from the module-level docstring
    in each source file, if present.
    """
    lines: list[str] = [
        "# NOTE: This file is generated by scripts/build.py.",
        "# The source code lives in src/openai_responses_manifold/ as multiple modules.",
        "# At build time, those modules are bundled into this single file for Open WebUI.",
        "# For the development layout and more details, see README.md.",
        "#",
        "# Logical module layout (source → sections below):",
    ]

    if not MODULE_ORDER:
        return "\n".join(lines)

    max_name_len = max(len(m) for m in MODULE_ORDER)

    for rel_path in MODULE_ORDER:
        desc = _get_module_docstring(rel_path)
        padded = rel_path.ljust(max_name_len)
        if desc:
            lines.append(f"# - {padded}  {desc}")
        else:
            lines.append(f"# - {rel_path}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Source cleaning / import stripping
# ---------------------------------------------------------------------------

@dataclass
class InternalImportStmt:
    """Representation of a single internal import statement in a module."""
    start_line: int
    end_line: int
    indent: str
    text_lines: list[str]
    alias_lines: list[str]


def clean_module_source(module_path: Path) -> str:
    """
    Read a module's source, apply transformations, and return cleaned text.

    Transformations:
    - Normalize line endings.
    - Remove `from __future__ import ...` statements.
    - Strip or comment out internal imports (within the package).
    - Inject alias lines for `from x import y as z` so `z` remains defined.
    - Collapse excessive blank lines.
    """
    source = module_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    source = _strip_future_imports(source)
    source, alias_lines = _strip_internal_imports(source)
    source = _collapse_blank_lines(source).strip()
    if alias_lines:
        source = _inject_alias_lines(source, alias_lines)
        source = _collapse_blank_lines(source).strip()
    return source


def _strip_future_imports(source: str) -> str:
    """
    Remove `from __future__ import ...` imports from a single module.

    The monolith will insert a single `from __future__ import annotations`
    at the top; individual modules don't need their own future imports.
    """
    lines = source.splitlines()
    cleaned: list[str] = []
    drop_next_blank = False

    for line in lines:
        if FUTURE_IMPORT_RE.match(line):
            drop_next_blank = True
            continue

        if drop_next_blank:
            drop_next_blank = False
            # Skip a single blank line immediately after the import.
            if line.strip():
                cleaned.append(line)
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


def _strip_internal_imports(source: str) -> tuple[str, list[str]]:
    """
    Comment out package-internal imports, and generate alias lines for any
    `from X import Y as Z` cases so code using `Z` still works.

    Returns:
        cleaned_source, alias_lines
    """
    lines = source.splitlines()
    statements = _collect_internal_imports(source, lines)
    if not statements:
        return source, []

    alias_lines: list[str] = []
    cleaned: list[str] = []
    by_start_line = {stmt.start_line: stmt for stmt in statements}
    idx = 1
    header_active = False
    header_indent = ""

    while idx <= len(lines):
        stmt = by_start_line.get(idx)
        if stmt:
            indent = stmt.indent
            header_line = f"{indent}# [build.py] internal imports removed in monolith:"
            if (not header_active) or (indent != header_indent):
                cleaned.append(header_line)

            alias_lines.extend(stmt.alias_lines)
            for raw_line in stmt.text_lines:
                trimmed = raw_line[len(indent) :] if raw_line.startswith(indent) else raw_line
                cleaned.append(f"{indent}# {trimmed}".rstrip())

            idx = stmt.end_line + 1
            header_active = True
            header_indent = indent
            continue

        line = lines[idx - 1]
        cleaned.append(line)
        header_active = False
        header_indent = ""
        idx += 1

    return "\n".join(cleaned), alias_lines


def _collect_internal_imports(source: str, lines: list[str]) -> list[InternalImportStmt]:
    """
    Parse the module AST and collect all import statements that refer to
    internal modules within this package.

    Internal imports are identified by `_is_internal_import_node`.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    statements_by_start: dict[int, InternalImportStmt] = {}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if not _is_internal_import_node(node):
            continue

        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if start is None:
            continue
        if end is None:
            end = start

        start_idx = max(start - 1, 0)
        end_idx = min(end, len(lines))
        text_lines = lines[start_idx:end_idx]
        indent = _leading_whitespace(lines[start_idx]) if start_idx < len(lines) else ""
        alias_lines = _alias_lines_for_import("\n".join(text_lines))

        stmt = statements_by_start.get(start)
        if stmt:
            # Extend an existing multi-line statement if needed.
            stmt.end_line = max(stmt.end_line, end)
            end_idx = min(stmt.end_line, len(lines))
            stmt.text_lines = lines[start_idx:end_idx]
            stmt.alias_lines.extend(alias_lines)
        else:
            statements_by_start[start] = InternalImportStmt(
                start_line=start,
                end_line=end,
                indent=indent,
                text_lines=text_lines,
                alias_lines=alias_lines,
            )

    return [statements_by_start[key] for key in sorted(statements_by_start)]


def _is_internal_import_node(node: ast.AST) -> bool:
    """Return True if this import node refers to an internal module."""
    if isinstance(node, ast.ImportFrom):
        # Ignore future imports
        if node.module == "__future__":
            return False
        # Relative imports (e.g. from .core import X) are always internal.
        if node.level and node.level > 0:
            return True
        # Absolute import from an internal module
        if node.module and _is_internal_module_name(node.module):
            return True
        return False

    if isinstance(node, ast.Import):
        return all(_is_internal_module_name(alias.name) for alias in node.names)

    return False


def _is_internal_module_name(module_name: str) -> bool:
    """Check if `module_name` refers to a module inside this package."""
    if not module_name:
        return False

    # Absolute import of the package or its submodules.
    if module_name == PACKAGE_NAME or module_name.startswith(PACKAGE_PREFIX):
        return True

    base = module_name.split(".", 1)[0]
    if base in INTERNAL_MODULES or module_name in INTERNAL_MODULES:
        return True

    for prefix in INTERNAL_PREFIXES:
        if base == prefix or module_name.startswith(f"{prefix}."):
            return True

    return False


def _leading_whitespace(line: str) -> str:
    """Return the leading whitespace from a line."""
    match = re.match(r"\s*", line)
    return match.group(0) if match else ""


def _collapse_blank_lines(source: str, *, max_consecutive: int = 2) -> str:
    """
    Ensure we never emit more than `max_consecutive` empty lines in a row.

    This keeps the monolith compact and readable without losing logical
    separation between sections.
    """
    if max_consecutive < 1:
        return source

    lines = source.splitlines()
    collapsed: list[str] = []
    blank_count = 0

    for line in lines:
        if line.strip():
            blank_count = 0
            collapsed.append(line)
        else:
            blank_count += 1
            if blank_count <= max_consecutive:
                collapsed.append("")

    return "\n".join(collapsed)


def _alias_lines_for_import(statement: str) -> list[str]:
    """
    For `from X import Y as Z` style imports, generate alias lines like
    `Z = Y` so code that referenced `Z` still works after we strip the
    internal import.

    Applied only to internal imports that are being removed.
    """
    try:
        tree = ast.parse(statement)
    except SyntaxError:
        return []

    aliases: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.asname:
                base_name = alias.name.rsplit(".", 1)[-1]
                aliases.append(f"{alias.asname} = {base_name}")
    return aliases


def _inject_alias_lines(source: str, alias_lines: list[str]) -> str:
    """
    Inject alias assignments (e.g. `FooAlias = Foo`) near the top of the
    module, after any module-level docstring but before other code.

    This allows code that relied on `from X import Foo as FooAlias` to
    continue working in the monolith.
    """
    if not alias_lines:
        return source

    lines = source.splitlines()
    insert_idx = 0

    # Skip leading blank lines
    while insert_idx < len(lines) and not lines[insert_idx].strip():
        insert_idx += 1

    # Skip over a module-level docstring if present
    if insert_idx < len(lines) and lines[insert_idx].lstrip().startswith(('"""', "'''")):
        quote = lines[insert_idx].lstrip()[:3]
        idx = insert_idx
        line = lines[idx].lstrip()
        # Single-line docstring?
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


# ---------------------------------------------------------------------------
# Build / CLI entrypoint
# ---------------------------------------------------------------------------

def run_build() -> int:
    """
    Build the monolithic openai_responses_manifold.py file.

    Steps:
    - Render the manifest docstring from pyproject.toml.
    - Render the file tree comment for navigation (using module docstrings).
    - Append each module's cleaned source in MODULE_ORDER, separated by
      section headers.
    """
    log("Bundling openai_responses_manifold.py…")

    manifest_text = extract_manifest_block()
    manifest_block = f'"""\n{manifest_text}\n"""'

    file_tree_comment = _render_file_tree_comment()

    sections: List[str] = [
        manifest_block,
        "",
        file_tree_comment,
        "",
        "# fmt: off",
        "# Open WebUI runs Black on upload; disabling fmt keeps this bundle readable in that UI.",
        "",
        "from __future__ import annotations",
        "",
    ]

    for rel_path in MODULE_ORDER:
        module_path = PACKAGE_DIR / rel_path
        if not module_path.exists():
            raise RuntimeError(f"Module not found: {rel_path}")
        cleaned = clean_module_source(module_path)
        sections.append(f"# === {rel_path} ===")
        sections.append(cleaned)
        sections.append("")

    sections.append("# fmt: on")

    OUTPUT_FILE.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    log(f"Wrote {OUTPUT_FILE.relative_to(PIPE_ROOT)}")
    return 0


def run_pytest() -> int:
    """
    Run pytest in the project root (PIPE_ROOT/tests).

    Returns pytest's exit code. Non-zero indicates failure.
    """
    log("Running pytest…")
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests"], cwd=PIPE_ROOT)
    if proc.returncode != 0:
        log("Tests failed; aborting build.")
    return proc.returncode


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the build script."""
    parser = argparse.ArgumentParser(
        description="Bundle src/openai_responses_manifold/ into openai_responses_manifold.py"
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running pytest before building.",
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="Only run pytest (no build).",
    )
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
