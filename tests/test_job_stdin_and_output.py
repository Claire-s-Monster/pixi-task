"""Jobs run non-interactively (stdin = EOF) and full job output is readable (#45)."""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import MagicMock

import pytest

from adapters.background import BackgroundJobManager
from adapters.execution import PixiExecutionAdapter

READ_STDIN = [sys.executable, "-c", "import sys; print('STDIN=' + repr(sys.stdin.read()))"]


@pytest.fixture
def open_stdin():
    """Make fd 0 a pipe whose write end stays open, so an inherited stdin would block."""
    read_fd, write_fd = os.pipe()
    saved = os.dup(0)
    os.dup2(read_fd, 0)
    try:
        yield
    finally:
        os.dup2(saved, 0)
        for fd in (saved, read_fd, write_fd):
            os.close(fd)


def _wait_completed(manager, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.status(job_id)
        if status["status"] == "completed":
            return status
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not complete within {timeout}s")


def test_background_job_stdin_is_eof(tmp_path, open_stdin):
    manager = BackgroundJobManager(str(tmp_path))
    handle = manager.launch(READ_STDIN, str(tmp_path), None, "demo", "demo")
    status = _wait_completed(manager, handle["job_id"])
    assert "STDIN=''" in status["output_tail"]


def test_foreground_run_stdin_is_eof(tmp_path, open_stdin):
    adapter = PixiExecutionAdapter(MagicMock(), MagicMock(), MagicMock())
    stdout, _, exit_code, _ = adapter._execute_with_timeout(
        READ_STDIN, timeout_seconds=5, working_dir=str(tmp_path)
    )
    assert exit_code == 0
    assert "STDIN=''" in stdout


def test_read_output_returns_full_log(tmp_path):
    manager = BackgroundJobManager(str(tmp_path))
    handle = manager.launch(
        ["sh", "-c", "i=0; while [ $i -lt 500 ]; do echo line$i; i=$((i+1)); done"],
        str(tmp_path),
        None,
        "demo",
        "demo",
    )
    _wait_completed(manager, handle["job_id"])
    text = manager.read_output(handle["job_id"])
    assert text is not None
    assert text.splitlines()[0] == "line0" and text.splitlines()[-1] == "line499"


def test_read_output_from_disk_for_fresh_manager(tmp_path):
    manager = BackgroundJobManager(str(tmp_path))
    handle = manager.launch(["sh", "-c", "echo hello"], str(tmp_path), None, "demo", "demo")
    _wait_completed(manager, handle["job_id"])
    assert BackgroundJobManager(str(tmp_path)).read_output(handle["job_id"]) == "hello\n"


def test_read_output_replaces_invalid_utf8(tmp_path):
    manager = BackgroundJobManager(str(tmp_path))
    handle = manager.launch(
        ["sh", "-c", "printf 'a\\377b\\n'"], str(tmp_path), None, "demo", "demo"
    )
    _wait_completed(manager, handle["job_id"])
    assert manager.read_output(handle["job_id"]) == "a�b\n"


def test_read_output_unknown_or_invalid_job(tmp_path):
    manager = BackgroundJobManager(str(tmp_path))
    assert manager.read_output("0123456789ab") is None
    assert manager.read_output("../etc") is None


def test_read_output_deleted_file(tmp_path):
    manager = BackgroundJobManager(str(tmp_path))
    handle = manager.launch(["sh", "-c", "echo hi"], str(tmp_path), None, "demo", "demo")
    status = _wait_completed(manager, handle["job_id"])
    os.unlink(status["output_file"])
    assert manager.read_output(handle["job_id"]) is None


def test_adapter_read_job_output_delegates(tmp_path):
    jobs = BackgroundJobManager(str(tmp_path))
    adapter = PixiExecutionAdapter(MagicMock(), MagicMock(), MagicMock(), jobs)
    handle = jobs.launch(["sh", "-c", "echo via-adapter"], str(tmp_path), None, "demo", "demo")
    _wait_completed(jobs, handle["job_id"])
    assert adapter.read_job_output(handle["job_id"]) == "via-adapter\n"
    assert adapter.read_job_output("0123456789ab") is None
