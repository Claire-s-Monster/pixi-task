"""Tests for adapters.git_snapshot on a real temporary git repository (issue #44)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from adapters.git_snapshot import changed_since, is_git_work_tree, take_snapshot


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "a.txt").write_text("a\n")
    (root / "b.txt").write_text("b\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_is_git_work_tree(repo, tmp_path):
    assert is_git_work_tree(str(repo)) is True
    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_git_work_tree(str(plain)) is False


def test_snapshot_is_json_serialisable(repo):
    (repo / "new.txt").write_text("n\n")
    snap = take_snapshot(str(repo))
    assert json.loads(json.dumps(snap)) == snap
    assert snap["head"] == _git(repo, "rev-parse", "HEAD").strip()
    assert set(snap["dirty"]) == {"new.txt"}


def test_no_change(repo):
    before = take_snapshot(str(repo))
    assert changed_since(str(repo), before) == []


def test_modified_tracked_file(repo):
    before = take_snapshot(str(repo))
    (repo / "a.txt").write_text("changed\n")
    assert changed_since(str(repo), before) == ["a.txt"]


def test_new_untracked_file(repo):
    before = take_snapshot(str(repo))
    (repo / "sub").mkdir()
    (repo / "sub" / "new.txt").write_text("x\n")
    assert changed_since(str(repo), before) == ["sub/new.txt"]


def test_already_dirty_then_modified_again(repo):
    (repo / "a.txt").write_text("first\n")
    before = take_snapshot(str(repo))
    (repo / "a.txt").write_text("second\n")
    assert changed_since(str(repo), before) == ["a.txt"]


def test_already_dirty_unchanged(repo):
    (repo / "a.txt").write_text("first\n")
    (repo / "untracked.txt").write_text("u\n")
    before = take_snapshot(str(repo))
    assert changed_since(str(repo), before) == []


def test_deleted_file_counts(repo):
    before = take_snapshot(str(repo))
    (repo / "b.txt").unlink()
    assert changed_since(str(repo), before) == ["b.txt"]


def test_dirty_file_reverted_counts(repo):
    (repo / "a.txt").write_text("dirty\n")
    before = take_snapshot(str(repo))
    _git(repo, "checkout", "--", "a.txt")
    assert changed_since(str(repo), before) == ["a.txt"]


def test_new_commit_paths_included(repo):
    before = take_snapshot(str(repo))
    (repo / "a.txt").write_text("committed\n")
    (repo / "c.txt").write_text("c\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "auto")
    assert changed_since(str(repo), before) == ["a.txt", "c.txt"]


def test_commit_plus_later_working_tree_change(repo):
    before = take_snapshot(str(repo))
    (repo / "a.txt").write_text("committed\n")
    _git(repo, "commit", "-q", "-am", "auto")
    (repo / "b.txt").write_text("after commit\n")
    assert changed_since(str(repo), before) == ["a.txt", "b.txt"]


def test_rename_entries_are_parsed(repo):
    _git(repo, "mv", "a.txt", "renamed.txt")
    snap = take_snapshot(str(repo))
    assert "renamed.txt" in snap["dirty"]
    assert snap["dirty"]["a.txt"] is None  # old path is gone
    assert set(snap["dirty"]) == {"renamed.txt", "a.txt"}


def test_subdirectory_repo_paths_are_root_relative(repo):
    sub = repo / "pkg"
    sub.mkdir()
    (sub / "f.txt").write_text("f\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pkg")
    before = take_snapshot(str(sub))
    (sub / "f.txt").write_text("changed\n")
    assert changed_since(str(sub), before) == ["pkg/f.txt"]


def test_unborn_head_new_commit(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "commit.gpgsign", "false")
    before = take_snapshot(str(root))
    assert before["head"] is None
    (root / "x.txt").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    assert changed_since(str(root), before) == ["x.txt"]
