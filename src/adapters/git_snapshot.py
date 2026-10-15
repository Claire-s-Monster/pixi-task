"""Git working-tree snapshots used to report what a command changed (issue #44).

A snapshot records HEAD plus a content hash for every dirty path, so a later
``changed_since`` can tell files the command touched apart from files that were
already dirty beforehand. All git calls use list argv (shell=False).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from core.process import run_with_group_kill

GIT_TIMEOUT_S = 60


def _git(repo: str, *args: str, check: bool = True) -> tuple[int, str]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git executable not found on PATH")
    result = run_with_group_kill([git, *args], timeout=GIT_TIMEOUT_S, cwd=repo)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.returncode, result.stdout


def is_git_work_tree(repo: str) -> bool:
    """True when ``repo`` is inside a git work tree."""
    try:
        code, out = _git(repo, "rev-parse", "--is-inside-work-tree", check=False)
    except (OSError, RuntimeError):
        return False
    return code == 0 and out.strip() == "true"


def current_head(repo: str) -> str | None:
    """Current HEAD commit sha, or None for an unborn branch."""
    code, out = _git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False)
    return out.strip() if code == 0 else None


def _porcelain_paths(raw: str) -> list[str]:
    """Paths from ``git status --porcelain=v1 -z``; rename/copy sources included."""
    paths: list[str] = []
    tokens = raw.split("\0")
    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if len(token) < 4:
            continue
        paths.append(token[3:])
        if token[0] in "RC" or token[1] in "RC":
            if i < len(tokens) and tokens[i]:
                paths.append(tokens[i])  # original path, now gone
            i += 1
    return paths


def _blob_hash(toplevel: str, path: str) -> str | None:
    if not (Path(toplevel) / path).is_file():
        return None
    code, out = _git(toplevel, "hash-object", "--", path, check=False)
    return out.strip() if code == 0 else None


def take_snapshot(repo: str) -> dict[str, Any]:
    """Record HEAD and ``{path: blob_hash_or_None}`` for every dirty path.

    Paths are relative to the repository root. ``None`` means the path no
    longer exists in the working tree.
    """
    _, top = _git(repo, "rev-parse", "--show-toplevel")
    toplevel = top.strip()
    _, status = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    dirty = {path: _blob_hash(toplevel, path) for path in _porcelain_paths(status)}
    return {"head": current_head(repo), "dirty": dirty}


def changed_since(repo: str, before: dict[str, Any]) -> list[str]:
    """Sorted paths committed or modified in the working tree since ``before``."""
    changed: set[str] = set()
    after = take_snapshot(repo)
    if after["head"] != before["head"] and after["head"] is not None:
        if before["head"] is None:  # first commit: everything in it is new
            _, out = _git(repo, "ls-tree", "-r", "--name-only", "--full-tree", "-z", "HEAD")
        else:
            _, out = _git(repo, "diff", "--name-only", "-z", before["head"], "HEAD")
        changed.update(p for p in out.split("\0") if p)
    old: dict[str, str | None] = before["dirty"]
    new: dict[str, str | None] = after["dirty"]
    for path in old.keys() | new.keys():
        if path not in old or path not in new or old[path] != new[path]:
            changed.add(path)
    return sorted(changed)
