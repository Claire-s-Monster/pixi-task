"""Tests for the pixi_exec allowlist config loader (issue #43)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import (
    DEFAULT_EXEC_ALLOWLIST,
    load_exec_allowlist,
    server_pyproject_path,
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(body)
    return path


def test_missing_file_returns_default(tmp_path):
    assert load_exec_allowlist(tmp_path / "nope.toml") == frozenset(DEFAULT_EXEC_ALLOWLIST)


def test_no_table_returns_default(tmp_path):
    path = _write(tmp_path, '[project]\nname = "x"\n')
    assert load_exec_allowlist(path) == frozenset(DEFAULT_EXEC_ALLOWLIST)


def test_table_without_key_returns_default(tmp_path):
    path = _write(tmp_path, "[tool.pixi-task]\nother = 1\n")
    assert load_exec_allowlist(path) == frozenset(DEFAULT_EXEC_ALLOWLIST)


def test_table_list_is_used(tmp_path):
    path = _write(tmp_path, '[tool.pixi-task]\nexec_allowlist = ["a", "b.c", "d_e-f"]\n')
    assert load_exec_allowlist(path) == frozenset({"a", "b.c", "d_e-f"})


def test_empty_list_allows_nothing(tmp_path):
    path = _write(tmp_path, "[tool.pixi-task]\nexec_allowlist = []\n")
    assert load_exec_allowlist(path) == frozenset()


@pytest.mark.parametrize(
    "value",
    ['"rattler-build"', '["a/b"]', '["../x"]', '["-x"]', "[3]", '[""]', '["a b"]'],
)
def test_invalid_values_raise(tmp_path, value):
    path = _write(tmp_path, f"[tool.pixi-task]\nexec_allowlist = {value}\n")
    with pytest.raises(ValueError):
        load_exec_allowlist(path)


def test_invalid_entry_is_named_in_error(tmp_path):
    path = _write(tmp_path, '[tool.pixi-task]\nexec_allowlist = ["ok", "a/b"]\n')
    with pytest.raises(ValueError, match="a/b"):
        load_exec_allowlist(path)


def test_repo_pyproject_matches_default():
    assert server_pyproject_path().is_file()
    assert load_exec_allowlist(server_pyproject_path()) == frozenset(DEFAULT_EXEC_ALLOWLIST)
    import tomllib

    data = tomllib.loads(server_pyproject_path().read_text())
    assert tuple(data["tool"]["pixi-task"]["exec_allowlist"]) == DEFAULT_EXEC_ALLOWLIST
