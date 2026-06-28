from __future__ import annotations

import time

from adapters.background import BackgroundJobManager


def _wait_for_completion(manager, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.status(job_id)
        if status["status"] == "completed":
            return status
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not complete within {timeout}s")


def test_launch_returns_running_handle(tmp_path):
    mgr = BackgroundJobManager(base_dir=str(tmp_path))
    handle = mgr.launch(
        command=["sh", "-c", "echo hello; sleep 0.2"],
        working_dir=str(tmp_path),
        env=None,
        task_name="demo",
        command_line="sh -c 'echo hello'",
    )
    assert handle["status"] == "running"
    assert handle["job_id"]
    assert handle["pid"] > 0
    assert handle["output_file"].endswith("output.log")
    assert handle["task_name"] == "demo"


def test_completed_job_reports_exit_code_and_output(tmp_path):
    mgr = BackgroundJobManager(base_dir=str(tmp_path))
    handle = mgr.launch(
        command=["sh", "-c", "echo first; echo second; exit 3"],
        working_dir=str(tmp_path),
        env=None,
        task_name="demo",
        command_line="sh -c '...'",
    )
    status = _wait_for_completion(mgr, handle["job_id"])
    assert status["status"] == "completed"
    assert status["exit_code"] == 3
    assert status["success"] is False
    assert "second" in status["output_tail"]
    assert status["execution_time"] >= 0


def test_successful_job_marks_success(tmp_path):
    mgr = BackgroundJobManager(base_dir=str(tmp_path))
    handle = mgr.launch(
        command=["sh", "-c", "echo ok"],
        working_dir=str(tmp_path),
        env=None,
        task_name="demo",
        command_line="sh -c 'echo ok'",
    )
    status = _wait_for_completion(mgr, handle["job_id"])
    assert status["exit_code"] == 0
    assert status["success"] is True


def test_custom_output_file_is_used(tmp_path):
    out = tmp_path / "custom.log"
    mgr = BackgroundJobManager(base_dir=str(tmp_path))
    handle = mgr.launch(
        command=["sh", "-c", "echo wrote"],
        working_dir=str(tmp_path),
        env=None,
        task_name="demo",
        command_line="sh -c 'echo wrote'",
        output_file=str(out),
    )
    assert handle["output_file"] == str(out)
    _wait_for_completion(mgr, handle["job_id"])
    assert "wrote" in out.read_text()


def test_status_unknown_job(tmp_path):
    mgr = BackgroundJobManager(base_dir=str(tmp_path))
    status = mgr.status("does-not-exist")
    assert status["status"] == "unknown"


def test_status_survives_lost_in_memory_record(tmp_path):
    mgr = BackgroundJobManager(base_dir=str(tmp_path))
    handle = mgr.launch(
        command=["sh", "-c", "echo persisted; exit 0"],
        working_dir=str(tmp_path),
        env=None,
        task_name="demo",
        command_line="sh -c '...'",
        output_file=str(tmp_path / "out.log"),
    )
    _wait_for_completion(mgr, handle["job_id"])

    fresh = BackgroundJobManager(base_dir=str(tmp_path))
    status = fresh.status(handle["job_id"])
    assert status["status"] == "completed"
    assert status["exit_code"] == 0
    assert "persisted" in status["output_tail"]


def test_launch_error_on_missing_executable(tmp_path):
    mgr = BackgroundJobManager(base_dir=str(tmp_path))
    handle = mgr.launch(
        command=["this-executable-does-not-exist-xyz"],
        working_dir=str(tmp_path),
        env=None,
        task_name="demo",
        command_line="this-executable-does-not-exist-xyz",
    )
    assert handle["status"] == "error"
    assert "Failed to launch" in handle["error"]
