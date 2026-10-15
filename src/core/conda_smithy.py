"""Pure helpers for the conda-smithy tools (issue #44)."""

from __future__ import annotations

import re
from typing import Any

MAX_LINT_ITEMS = 50
# Kept low so the whole response stays under apply_token_limits' ~8000-char
# threshold, which would otherwise silently cut lists to 5 items.
MAX_CHANGED_FILES = 60
OUTPUT_TAIL_LINES = 30

_LINT_HEADER = re.compile(r"^.+ has some lint:$")
_HINT_HEADER = re.compile(r"^.+ (?:also )?has some suggestions:$")
_FINE_HEADER = re.compile(r"^.+ is in fine form$")
_ITEM_START = re.compile(r"^  \S")


def parse_recipe_lint(stdout: str) -> dict[str, Any]:
    """Parse ``conda-smithy recipe-lint`` stdout into lints, hints and leftovers.

    Items start with exactly two spaces then a non-space; deeper-indented or
    whitespace-only lines continue the previous item. Anything else that is
    non-empty and not a header is returned in ``unparsed``.
    """
    lints: list[str] = []
    hints: list[str] = []
    unparsed: list[str] = []
    fine = False
    target: list[str] | None = None
    item: list[str] | None = None

    def close_item() -> None:
        nonlocal item
        if item is not None and target is not None:
            while item and not item[-1]:
                item.pop()
            target.append("\n".join(item))
        item = None

    for raw in stdout.splitlines():
        line = raw.rstrip()
        if _LINT_HEADER.match(line):
            close_item()
            target = lints
        elif _HINT_HEADER.match(line):
            close_item()
            target = hints
        elif _FINE_HEADER.match(line):
            close_item()
            target = None
            fine = True
        elif _ITEM_START.match(raw) and target is not None:
            close_item()
            item = [raw[2:].rstrip()]
        elif item is not None and (not line or raw.startswith("   ")):
            item.append(line)
        elif line:
            close_item()
            target = None
            unparsed.append(line)
    close_item()
    return {"lints": lints, "hints": hints, "fine": fine, "unparsed": unparsed}


def count_by_top_dir(paths: list[str]) -> dict[str, int]:
    """Count paths per top-level directory ("." for files in the repo root)."""
    counts: dict[str, int] = {}
    for path in paths:
        top = path.split("/", 1)[0] if "/" in path else "."
        counts[top] = counts.get(top, 0) + 1
    return dict(sorted(counts.items()))


def output_tail(stdout: str, stderr: str, lines: int = OUTPUT_TAIL_LINES) -> str:
    """Last ``lines`` lines of combined stdout+stderr."""
    combined = "\n".join(part for part in (stdout.rstrip(), stderr.rstrip()) if part)
    return "\n".join(combined.splitlines()[-lines:])
