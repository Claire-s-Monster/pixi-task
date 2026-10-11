"""Timeouts must kill the whole process group, not just the direct child (#34)."""

import os
import signal
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from adapters.execution import PixiExecutionAdapter

GRANDCHILD_SCRIPT = "sleep 60 & echo $! > {pidfile}; wait"


def _alive(pid: int) -> bool:
    """True if pid exists and is not a zombie."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("State:"):
                return "Z" not in line.split()[1]
    except OSError:
        return False
    return True


def _wait_gone(pid: int, wait: float = 5.0) -> bool:
    deadline = time.time() + wait
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


def _read_pid(pidfile: Path) -> int:
    deadline = time.time() + 5
    while time.time() < deadline:
        text = pidfile.read_text().strip() if pidfile.exists() else ""
        if text:
            return int(text)
        time.sleep(0.02)
    raise AssertionError("grandchild pid file never written")


def _adapter() -> PixiExecutionAdapter:
    return PixiExecutionAdapter(MagicMock(), MagicMock(), MagicMock(), MagicMock())


def test_execution_timeout_kills_grandchild(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    command = ["sh", "-c", GRANDCHILD_SCRIPT.format(pidfile=pidfile)]
    pid = None
    try:
        stdout, stderr, code, _ = _adapter()._execute_with_timeout(command, 1)
        pid = _read_pid(pidfile)
        assert code == 124
        assert stdout == ""
        assert "timed out after 1 seconds" in stderr
        assert _wait_gone(pid), "grandchild outlived the timeout"
    finally:
        if pid is None and pidfile.exists() and pidfile.read_text().strip():
            pid = int(pidfile.read_text().strip())
        if pid is not None and _alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_helper_raises_timeout_and_kills_grandchild(tmp_path: Path) -> None:
    from core.process import run_with_group_kill

    pidfile = tmp_path / "pid"
    command = ["sh", "-c", GRANDCHILD_SCRIPT.format(pidfile=pidfile)]
    pid = None
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_with_group_kill(command, timeout=1)
        pid = _read_pid(pidfile)
        assert _wait_gone(pid), "grandchild outlived the timeout"
    finally:
        if pid is None and pidfile.exists() and pidfile.read_text().strip():
            pid = int(pidfile.read_text().strip())
        if pid is not None and _alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_helper_returns_output_unchanged(tmp_path: Path) -> None:
    from core.process import run_with_group_kill

    result = run_with_group_kill(
        ["sh", "-c", "echo out; echo err >&2; exit 3"], timeout=10, cwd=str(tmp_path)
    )
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert result.returncode == 3


def test_execution_fast_command_unchanged() -> None:
    stdout, stderr, code, _ = _adapter()._execute_with_timeout(["sh", "-c", "echo hi; exit 0"], 10)
    assert (stdout, stderr, code) == ("hi\n", "", 0)
