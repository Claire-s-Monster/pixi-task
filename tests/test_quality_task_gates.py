"""Regression tests for GitHub issue #18: `quality` task missing `format-check`.

Before the fix, pyproject.toml's `quality` task depended-on only
`["test", "lint", "typecheck"]`, so ruff-format drift was never gated
locally. This regressed twice (PR #13 fixed the symptom; it came back
within ten days) because nothing asserted on the actual task graph.
These tests parse pyproject.toml directly so a future edit that drops
`format-check` again fails CI immediately.
"""

from __future__ import annotations

import pathlib
import tomllib


def _load_pyproject() -> dict:
    """Locate and parse pyproject.toml relative to this file, not cwd."""
    current = pathlib.Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            with candidate.open("rb") as fh:
                return tomllib.load(fh)
    raise FileNotFoundError("pyproject.toml not found above tests/test_quality_task_gates.py")


def _tasks() -> dict:
    return _load_pyproject()["tool"]["pixi"]["tasks"]


def test_quality_task_depends_on_format_check():
    quality_task = _tasks()["quality"]
    assert "format-check" in quality_task["depends-on"], (
        "quality task must gate on format-check to catch ruff-format drift (see GitHub issue #18)"
    )


def test_quality_task_still_depends_on_existing_gates():
    """Guard against a future fix regressing by replacing rather than adding."""
    depends_on = _tasks()["quality"]["depends-on"]
    for required in ("lint", "typecheck", "test"):
        assert required in depends_on, f"quality task lost existing dependency: {required}"


def test_format_check_task_exists_and_invokes_ruff_format_check():
    tasks = _tasks()
    assert "format-check" in tasks, "format-check task must exist"
    format_check = tasks["format-check"]
    # format-check is a plain string command in pyproject.toml.
    cmd = format_check if isinstance(format_check, str) else format_check.get("cmd", "")
    assert "ruff format --check" in cmd, (
        f"format-check task must invoke 'ruff format --check', got: {cmd!r}"
    )
