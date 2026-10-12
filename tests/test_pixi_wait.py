"""Tests for pixi_wait (issue #31): bounded long-poll on background jobs."""

from __future__ import annotations

import json
import math
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from adapters import background
from adapters.background import BackgroundJobManager
from core.pixi_service import PixiShellService
from pixi_task.lean_mcp_interface import LeanMCPInterface

POLL = background.WAIT_POLL_INTERVAL_S


@pytest.fixture
def manager(tmp_path: Path) -> BackgroundJobManager:
    return BackgroundJobManager(str(tmp_path / "jobs"))


def _fake_job(
    manager: BackgroundJobManager,
    job_id: str = "fake1",
    status: str = "completed",
    exit_code: int | None = 0,
    log: str = "",
    pid: int | None = None,
) -> Path:
    """Create an on-disk job (no in-memory record), as after a server restart."""
    import os

    job_dir = manager._base / job_id
    job_dir.mkdir(parents=True)
    out = job_dir / "output.log"
    out.write_text(log)
    (job_dir / "status.json").write_text(
        json.dumps(
            {
                "status": status,
                "job_id": job_id,
                "pid": pid if pid is not None else os.getpid(),
                "output_file": str(out),
                "exit_code": exit_code,
            }
        )
    )
    return job_dir


def test_running_job_returns_waiting_after_wait_expired(manager):
    _fake_job(manager, status="running", exit_code=None)
    start = time.monotonic()
    result = manager.wait("fake1", wait_s=0.4)
    took = time.monotonic() - start
    assert result["state"] == "waiting"
    assert result["returned_because"] == "wait_expired"
    assert result["job_status"] == "running"
    assert 0.35 <= took <= 0.4 + POLL + 0.3
    assert result["elapsed_s"] == pytest.approx(took, abs=0.2)


def test_job_finishing_mid_wait_returns_completed_early(manager):
    launched = manager.launch(
        ["sh", "-c", "sleep 0.5; echo '3 passed'"], None, None, "t", "sh -c ..."
    )
    start = time.monotonic()
    result = manager.wait(launched["job_id"], wait_s=10, result_contains=[" passed"])
    took = time.monotonic() - start
    assert took < 5
    assert result["state"] == "done"
    assert result["returned_because"] == "completed"
    assert result["job_status"] == "completed"
    assert result["exit_code"] == 0
    assert result["matched_lines"] == ["3 passed"]
    assert result["output_file"] == launched["output_file"]


def test_failed_job_without_matches_still_reports_status_and_exit_code(manager):
    _fake_job(manager, exit_code=2, log="nothing interesting\n")
    result = manager.wait("fake1", wait_s=0, result_contains=["FAILED"])
    assert result["state"] == "done"
    assert result["job_status"] == "completed"
    assert result["exit_code"] == 2
    assert result["matched_lines"] == []


def test_dead_launcher_unknown_status_is_done_not_waiting(manager):
    _fake_job(manager, status="running", exit_code=None, pid=2**22 + 12345)
    result = manager.wait("fake1", wait_s=5)
    assert result["state"] == "done"
    assert result["job_status"] == "unknown"
    assert "exit_code" in result


def test_matched_lines_only_matching_and_capped_keeping_last(manager):
    log = "\n".join(f"ERROR number {i}" if i % 2 else f"ok {i}" for i in range(40)) + "\n"
    _fake_job(manager, log=log)
    result = manager.wait("fake1", wait_s=0, result_contains=["ERROR"], max_result_lines=5)
    assert result["matched_lines"] == [f"ERROR number {i}" for i in (31, 33, 35, 37, 39)]


def test_matched_lines_read_from_bounded_tail_only(manager):
    early = "EARLY_MARKER FAILED\n"
    filler = ("x" * 99 + "\n") * (3 * background.TAIL_BYTES // 100)
    _fake_job(manager, log=early + filler + "LATE_MARKER FAILED\n")
    result = manager.wait("fake1", wait_s=0, result_contains=["FAILED"], max_result_lines=100)
    assert result["matched_lines"] == ["LATE_MARKER FAILED"]


def test_partial_first_line_of_tail_is_dropped(manager):
    tail = background.TAIL_BYTES
    # A matching line straddling the window start must not be returned truncated.
    line = "FAILED " + "y" * 200 + "\n"
    log = "a" * (tail - 100) + "\n" + line + "z FAILED\n"
    _fake_job(manager, log=log)
    result = manager.wait("fake1", wait_s=0, result_contains=["FAILED"], max_result_lines=100)
    assert "z FAILED" in result["matched_lines"]
    assert all(len(m) in (len(line) - 1, len("z FAILED")) for m in result["matched_lines"])


def test_no_result_contains_gives_empty_matched_lines_never_raw_tail(manager):
    _fake_job(manager, log="secret raw output\n")
    result = manager.wait("fake1", wait_s=0)
    assert result["state"] == "done"
    assert result["matched_lines"] == []
    assert "secret raw output" not in json.dumps(result)


def test_matching_is_plain_substring_not_regex(manager):
    _fake_job(manager, log="abc\na.c\n")
    result = manager.wait("fake1", wait_s=0, result_contains=["a.c"])
    assert result["matched_lines"] == ["a.c"]


def test_wait_s_zero_checks_once(manager):
    _fake_job(manager, status="running", exit_code=None)
    start = time.monotonic()
    result = manager.wait("fake1", wait_s=0)
    assert time.monotonic() - start < 0.3
    assert result["state"] == "waiting"
    assert result["returned_because"] == "wait_expired"


def test_wait_s_clamped_to_max(manager, monkeypatch):
    monkeypatch.setattr(background, "MAX_WAIT_S", 0.4)
    _fake_job(manager, status="running", exit_code=None)
    start = time.monotonic()
    result = manager.wait("fake1", wait_s=10_000)
    took = time.monotonic() - start
    assert result["state"] == "waiting"
    assert took <= 0.4 + POLL + 0.3


def test_negative_wait_s_clamped_to_zero(manager):
    _fake_job(manager, status="running", exit_code=None)
    start = time.monotonic()
    assert manager.wait("fake1", wait_s=-5)["state"] == "waiting"
    assert time.monotonic() - start < 0.3


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_wait_s_is_error(manager, bad):
    _fake_job(manager)
    result = manager.wait("fake1", wait_s=bad)
    assert result["state"] == "error"
    assert result["returned_because"] == "error"
    assert "wait_s" in result["error"]


@pytest.mark.parametrize(
    "needles",
    [["x"] * 11, ["a" * 257], [""], ["ok", ""]],
)
def test_invalid_result_contains_is_error(manager, needles):
    _fake_job(manager)
    result = manager.wait("fake1", wait_s=0, result_contains=needles)
    assert result["state"] == "error"
    assert "result_contains" in result["error"]


def test_result_contains_limits_boundaries_accepted(manager):
    _fake_job(manager, log="hit\n")
    result = manager.wait("fake1", wait_s=0, result_contains=["hit"] * 10 + [])
    assert result["state"] == "done"
    result = manager.wait("fake1", wait_s=0, result_contains=["a" * 256])
    assert result["state"] == "done"


def test_max_result_lines_clamped(manager):
    _fake_job(manager, log="".join(f"hit {i}\n" for i in range(300)))
    assert len(manager.wait("fake1", 0, ["hit"], max_result_lines=10_000)["matched_lines"]) == 100
    assert len(manager.wait("fake1", 0, ["hit"], max_result_lines=0)["matched_lines"]) == 1
    assert len(manager.wait("fake1", 0, ["hit"])["matched_lines"]) == 25


def test_unknown_job_id_is_error_not_a_wait(manager):
    start = time.monotonic()
    result = manager.wait("nope", wait_s=5)
    assert time.monotonic() - start < 1
    assert result["state"] == "error"
    assert result["returned_because"] == "error"
    assert "nope" in result["error"]


def test_deleted_job_dir_is_error(manager):
    launched = manager.launch(["sh", "-c", "sleep 0.1"], None, None, "t", "sleep")
    manager.wait(launched["job_id"], wait_s=5)
    shutil.rmtree(manager._base / launched["job_id"])
    result = manager.wait(launched["job_id"], wait_s=5)
    assert result["state"] == "error"


def test_job_dir_deleted_while_waiting_is_error(manager):
    job_dir = _fake_job(manager, status="running", exit_code=None)
    threading.Timer(0.2, shutil.rmtree, args=(job_dir,)).start()
    start = time.monotonic()
    result = manager.wait("fake1", wait_s=5)
    assert time.monotonic() - start < 3
    assert result["state"] == "error"


def test_missing_status_file_is_error(manager):
    job_dir = _fake_job(manager)
    (job_dir / "status.json").unlink()
    assert manager.wait("fake1", wait_s=5)["state"] == "error"


def test_concurrency_cap_does_single_nonwaiting_check(manager):
    _fake_job(manager, status="running", exit_code=None)
    for _ in range(background.MAX_CONCURRENT_WAITS):
        assert manager._wait_slots.acquire(blocking=False)
    try:
        start = time.monotonic()
        result = manager.wait("fake1", wait_s=10)
        assert time.monotonic() - start < 0.3
    finally:
        for _ in range(background.MAX_CONCURRENT_WAITS):
            manager._wait_slots.release()
    assert result["state"] == "waiting"
    assert result["returned_because"] == "concurrency_cap"


def test_concurrency_cap_still_reports_done_jobs(manager):
    _fake_job(manager, exit_code=0)
    for _ in range(background.MAX_CONCURRENT_WAITS):
        manager._wait_slots.acquire(blocking=False)
    try:
        result = manager.wait("fake1", wait_s=10)
    finally:
        for _ in range(background.MAX_CONCURRENT_WAITS):
            manager._wait_slots.release()
    assert result["state"] == "done"
    assert result["returned_because"] == "completed"


def test_semaphore_released_after_each_call(manager):
    _fake_job(manager, status="running", exit_code=None)
    for _ in range(background.MAX_CONCURRENT_WAITS + 2):
        assert manager.wait("fake1", wait_s=0)["returned_because"] == "wait_expired"
    manager.wait("missing", wait_s=0)
    for _ in range(background.MAX_CONCURRENT_WAITS):
        assert manager._wait_slots.acquire(blocking=False)


def test_invalid_status_json_midrun_keeps_waiting_until_valid(manager):
    job_dir = _fake_job(manager, status="running", exit_code=None)
    status_path = job_dir / "status.json"
    status_path.write_text('{"status": "comp')  # half-written

    def finish() -> None:
        status_path.write_text(
            json.dumps({"status": "completed", "job_id": "fake1", "exit_code": 0})
        )

    threading.Timer(0.3, finish).start()
    result = manager.wait("fake1", wait_s=5)
    assert result["state"] == "done"
    assert result["exit_code"] == 0


def test_persistently_invalid_status_json_is_waiting_not_error(manager):
    job_dir = _fake_job(manager)
    (job_dir / "status.json").write_text("{")
    result = manager.wait("fake1", wait_s=0.2)
    assert result["state"] == "waiting"
    assert result["returned_because"] == "wait_expired"


def test_status_writer_is_atomic(tmp_path):
    target = tmp_path / "status.json"
    BackgroundJobManager._write_status(target, {"a": 1})
    BackgroundJobManager._write_status(target, {"a": 2})
    assert json.loads(target.read_text()) == {"a": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["status.json"]


def test_status_writer_uses_replace(tmp_path, monkeypatch):
    calls = []
    real = background.os.replace
    monkeypatch.setattr(background.os, "replace", lambda a, b: (calls.append((a, b)), real(a, b)))
    target = tmp_path / "status.json"
    BackgroundJobManager._write_status(target, {"a": 1})
    assert len(calls) == 1 and Path(calls[0][1]) == target


def test_service_delegates_to_executor():
    executor = SimpleNamespace(wait_for_job=lambda *a, **k: {"state": "done", "args": a})
    service = PixiShellService.__new__(PixiShellService)
    service.pixi_executor = executor
    assert service.wait_for_job("j", 1.0, ["x"], 5)["state"] == "done"


def test_tool_registered_with_schema_and_examples():
    iface = LeanMCPInterface(SimpleNamespace())
    entry = iface.tool_registry["pixi_wait"]
    props = entry["schema"]["properties"]
    assert entry["schema"]["required"] == ["job_id"]
    assert props["wait_s"]["default"] == 15
    assert props["max_result_lines"]["default"] == 25
    assert props["result_contains"]["maxItems"] == 10
    assert any(
        e.get("result_contains") == ["FAILED", "ERROR", " passed", " failed"]
        for e in entry["examples"]
    )


def test_through_real_dispatch_path(tmp_path):
    manager = BackgroundJobManager(str(tmp_path / "jobs"))
    launched = manager.launch(
        ["sh", "-c", "sleep 0.3; echo '3 passed'; exit 1"], None, None, "t", "sh"
    )
    service = PixiShellService.__new__(PixiShellService)
    service.pixi_executor = SimpleNamespace(wait_for_job=lambda *a, **k: manager.wait(*a, **k))
    iface = LeanMCPInterface(SimpleNamespace(pixi_service=service))
    response = iface.dispatch_meta_tool(
        "execute_tool",
        {
            "tool_name": "pixi_wait",
            "parameters": {
                "job_id": launched["job_id"],
                "wait_s": 10,
                "result_contains": ["FAILED", "ERROR", " passed", " failed"],
            },
        },
    )
    assert response["status"] == "success", response
    result = response["result"]
    assert result["state"] == "done"
    assert result["exit_code"] == 1
    assert result["matched_lines"] == ["3 passed"]
    assert result["returned_because"] == "completed"


def test_dispatch_rejects_unknown_param():
    iface = LeanMCPInterface(SimpleNamespace(pixi_service=SimpleNamespace()))
    response = iface.dispatch_meta_tool(
        "execute_tool",
        {"tool_name": "pixi_wait", "parameters": {"job_id": "j", "regex": "x"}},
    )
    assert response["status"] == "error"
