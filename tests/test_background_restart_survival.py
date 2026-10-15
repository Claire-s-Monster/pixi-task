"""Issue #52: background jobs must survive a server restart.

Unit tests need no systemd. The integration tests drive a real transient
systemd user service and are skipped when a user manager is unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

from adapters import background
from adapters.background import BackgroundJobManager, should_use_scope, wrap_command


def _wait_done(mgr, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = mgr.status(job_id)
        if st["status"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError("job still running")


@pytest.fixture(autouse=True)
def _no_scope(monkeypatch):
    monkeypatch.setenv("PIXI_TASK_JOB_SCOPE", "never")


def _launch(mgr, command, tmp_path):
    return mgr.launch(
        command=command,
        working_dir=str(tmp_path),
        env=None,
        task_name="t",
        command_line=" ".join(command),
    )


# ----- wrapper ---------------------------------------------------------------


@pytest.mark.parametrize("rc", [0, 3])
def test_wrapper_writes_exit_code(tmp_path, rc):
    mgr = BackgroundJobManager(base_dir=str(tmp_path / "jobs"))
    handle = _launch(mgr, ["sh", "-c", f"echo hi; exit {rc}"], tmp_path)
    st = _wait_done(mgr, handle["job_id"])
    exit_file = tmp_path / "jobs" / handle["job_id"] / "exit_code"
    assert exit_file.read_text() == str(rc)
    assert st["exit_code"] == rc
    assert "hi" in st["output_tail"]
    assert not list(exit_file.parent.glob("exit_code.tmp"))


def test_wrapper_preserves_args_with_spaces_and_quotes(tmp_path):
    awkward = "a b 'c' \"d\" $HOME `x` ;rm"
    mgr = BackgroundJobManager(base_dir=str(tmp_path / "jobs"))
    handle = _launch(
        mgr, [sys.executable, "-c", "import sys; print(sys.argv[1])", awkward], tmp_path
    )
    st = _wait_done(mgr, handle["job_id"])
    assert st["exit_code"] == 0
    assert awkward in st["output_tail"]


def test_wrap_command_shape():
    wrapped = wrap_command(["echo", "x y"], Path("/j/exit_code"))
    assert wrapped[:2] == ["/bin/sh", "-c"]
    assert wrapped[3] == "/j/exit_code"
    assert wrapped[4:] == ["echo", "x y"]


def test_finalize_prefers_exit_file(tmp_path):
    mgr = BackgroundJobManager(base_dir=str(tmp_path / "jobs"))
    handle = _launch(mgr, ["sh", "-c", "exit 0"], tmp_path)
    st = _wait_done(mgr, handle["job_id"])
    assert st["exit_code"] == 0 and st["success"] is True
    assert st["scope"] is False


# ----- scope decision --------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "have", "in_unit", "expected"),
    [
        ("auto", True, True, True),
        ("auto", True, False, False),
        ("auto", False, True, False),
        ("auto", False, False, False),
        ("never", True, True, False),
        ("always", True, False, True),
        ("always", True, True, True),
        ("always", False, True, False),
        ("bogus", True, True, True),
        ("bogus", True, False, False),
        ("", True, True, True),
    ],
)
def test_should_use_scope(mode, have, in_unit, expected):
    assert should_use_scope(mode, have, in_unit) is expected


# ----- recovery --------------------------------------------------------------


def _write_running(base: Path, job_id: str, pid: int, pid_start: str | None = None) -> Path:
    job_dir = base / job_id
    job_dir.mkdir(parents=True)
    out = job_dir / "output.log"
    out.write_text("some output\n")
    (job_dir / "status.json").write_text(
        json.dumps(
            {
                "status": "running",
                "job_id": job_id,
                "pid": pid,
                "pid_start": pid_start,
                "task_name": "t",
                "command_line": "x",
                "working_dir": "/",
                "output_file": str(out),
                "started_at": "2026-01-01T00:00:00+00:00",
                "exit_code": None,
                "finished_at": None,
                "execution_time": None,
                "scope": False,
            }
        )
    )
    return job_dir


def _dead_pid() -> int:
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


@pytest.mark.parametrize(("rc", "success"), [(0, True), (5, False)])
def test_recovery_with_exit_file_is_completed(tmp_path, rc, success):
    job_dir = _write_running(tmp_path, "aaaaaaaaaaaa", _dead_pid())
    (job_dir / "exit_code").write_text(str(rc))
    st = BackgroundJobManager(base_dir=str(tmp_path)).status("aaaaaaaaaaaa")
    assert st["status"] == "completed"
    assert st["exit_code"] == rc
    assert st["success"] is success
    assert st["execution_time"] is not None and st["execution_time"] >= 0
    persisted = json.loads((job_dir / "status.json").read_text())
    assert persisted["status"] == "completed" and persisted["exit_code"] == rc
    assert persisted["finished_at"]
    assert "output_tail" not in persisted


def test_recovery_without_exit_file_is_killed(tmp_path):
    job_dir = _write_running(tmp_path, "bbbbbbbbbbbb", _dead_pid())
    st = BackgroundJobManager(base_dir=str(tmp_path)).status("bbbbbbbbbbbb")
    assert st["status"] == "killed"
    assert "without recording an exit code" in st["error"]
    assert st["retryable"] is False
    assert json.loads((job_dir / "status.json").read_text())["status"] == "killed"


def test_recovery_alive_pid_stays_running(tmp_path):
    proc = subprocess.Popen(["sleep", "30"])
    try:
        start = background.proc_start_time(proc.pid)
        assert start
        _write_running(tmp_path, "cccccccccccc", proc.pid, start)
        st = BackgroundJobManager(base_dir=str(tmp_path)).status("cccccccccccc")
        assert st["status"] == "running"
    finally:
        proc.kill()
        proc.wait()


def test_pid_reuse_guard_treats_different_start_time_as_dead(tmp_path):
    proc = subprocess.Popen(["sleep", "30"])
    try:
        real = background.proc_start_time(proc.pid)
        assert real
        _write_running(tmp_path, "dddddddddddd", proc.pid, str(int(real) + 1))
        st = BackgroundJobManager(base_dir=str(tmp_path)).status("dddddddddddd")
        assert st["status"] == "killed"
    finally:
        proc.kill()
        proc.wait()


def test_unknown_ids_stay_unknown(tmp_path):
    mgr = BackgroundJobManager(base_dir=str(tmp_path))
    assert mgr.status("eeeeeeeeeeee")["status"] == "unknown"
    assert mgr.status("../etc")["status"] == "unknown"


def test_wait_reports_killed_as_done_with_error(tmp_path):
    _write_running(tmp_path, "ffffffffffff", _dead_pid())
    res = BackgroundJobManager(base_dir=str(tmp_path)).wait("ffffffffffff", wait_s=1)
    assert res["state"] == "done"
    assert res["job_status"] == "killed"
    assert "without recording an exit code" in res["error"]


def test_proc_start_time_missing_pid():
    assert background.proc_start_time(_dead_pid()) is None


# ----- systemd-run failure fallback -----------------------------------------


def test_systemd_run_failure_falls_back_to_plain_launch(tmp_path, monkeypatch):
    fake_dir = tmp_path / "bin"
    fake_dir.mkdir()
    fake = fake_dir / "systemd-run"
    fake.write_text("#!/bin/sh\necho 'Failed to connect to bus: No medium found' >&2\nexit 1\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PIXI_TASK_JOB_SCOPE", "always")

    mgr = BackgroundJobManager(base_dir=str(tmp_path / "jobs"))
    handle = _launch(mgr, ["sh", "-c", "echo ran-plain"], tmp_path)
    assert handle["status"] == "running"
    assert handle["scope"] is False
    assert "Failed to connect" in handle["scope_error"]
    st = _wait_done(mgr, handle["job_id"])
    assert st["status"] == "completed" and st["exit_code"] == 0
    assert st["scope"] is False
    assert "ran-plain" in st["output_tail"]
    assert "Failed to connect" not in st["output_tail"]


def test_scoped_launch_prefixes_systemd_run(tmp_path, monkeypatch):
    captured = {}

    class FakeProc:
        pid = os.getpid()
        returncode = None

        def wait(self, timeout=None):
            if timeout is None:
                return 0
            raise subprocess.TimeoutExpired("x", timeout)

        def poll(self):
            return None

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProc()

    monkeypatch.setenv("PIXI_TASK_JOB_SCOPE", "always")
    monkeypatch.setattr(background.shutil, "which", lambda name, **kwargs: "/usr/bin/systemd-run")
    monkeypatch.setattr(background.subprocess, "Popen", fake_popen)
    mgr = BackgroundJobManager(base_dir=str(tmp_path))
    handle = _launch(mgr, ["echo", "hi"], tmp_path)
    cmd = captured["cmd"]
    assert cmd[:5] == ["systemd-run", "--user", "--scope", "--quiet", "--collect"]
    assert cmd[5] == f"--unit=pixi-task-job-{handle['job_id']}"
    assert cmd[6] == "--"
    assert cmd[7:9] == ["/bin/sh", "-c"]
    assert handle["scope"] is True


# ----- integration: real systemd ---------------------------------------------


def _systemd_user_ok() -> bool:
    if not shutil.which("systemd-run") or not shutil.which("systemctl"):
        return False
    try:
        out = subprocess.run(
            ["systemctl", "--user", "is-system-running"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.stdout.strip() in {"running", "degraded"}


needs_systemd = pytest.mark.skipif(not _systemd_user_ok(), reason="no systemd user manager")

HELPER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from adapters.background import BackgroundJobManager

    base, idfile = sys.argv[1], sys.argv[2]
    mgr = BackgroundJobManager(base_dir=base)
    h = mgr.launch(["sh", "-c", "sleep 3; echo DONE"], base, None, "t", "sleep 3; echo DONE")
    Path(idfile + ".tmp").write_text(h["job_id"] + " " + str(h["pid"]) + " " + str(h["scope"]))
    Path(idfile + ".tmp").rename(idfile)
    while True:
        time.sleep(60)
    """
)


def _stop(unit: str) -> None:
    subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True, timeout=30)
    subprocess.run(["systemctl", "--user", "reset-failed", unit], capture_output=True, timeout=30)


def _run_restart_case(tmp_path: Path, scope_mode: str) -> tuple[dict, str, str]:
    host = f"pixi-task-test-host-{uuid.uuid4().hex[:8]}"
    helper = tmp_path / "helper.py"
    helper.write_text(HELPER)
    idfile = tmp_path / "jobid"
    base = tmp_path / "jobs"
    src = str(Path(background.__file__).resolve().parents[1])
    job_id = ""
    try:
        subprocess.run(
            [
                "systemd-run",
                "--user",
                "--quiet",
                f"--unit={host}",
                "--property=KillMode=control-group",
                f"--setenv=PIXI_TASK_JOB_SCOPE={scope_mode}",
                f"--setenv=PYTHONPATH={src}",
                "--",
                sys.executable,
                str(helper),
                str(base),
                str(idfile),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        deadline = time.time() + 15
        while not idfile.exists() and time.time() < deadline:
            time.sleep(0.1)
        assert idfile.exists(), "helper never launched a job"
        job_id, pid, scope = idfile.read_text().split()
        if scope_mode == "auto":
            # systemd-run --scope must exec: Popen's pid is the wrapper shell itself,
            # living in its own pixi-task-job-<id>.scope cgroup.
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
            assert cmdline.startswith(b"/bin/sh\0-c\0"), cmdline
            assert f"pixi-task-job-{job_id}.scope" in Path(f"/proc/{pid}/cgroup").read_text()
        subprocess.run(["systemctl", "--user", "stop", host], check=True, timeout=30)
        mgr = BackgroundJobManager(base_dir=str(base))
        deadline = time.time() + 20
        st = mgr.status(job_id)
        while st["status"] == "running" and time.time() < deadline:
            time.sleep(0.2)
            st = mgr.status(job_id)
        return st, pid, scope
    finally:
        _stop(host)
        if job_id:
            _stop(f"pixi-task-job-{job_id}.scope")


@pytest.mark.integration
@needs_systemd
def test_job_survives_service_restart(tmp_path):
    st, pid, scope = _run_restart_case(tmp_path, "auto")
    assert scope == "True"
    assert st["status"] == "completed", st
    assert st["exit_code"] == 0
    assert "DONE" in st["output_tail"]
    assert st["pid"] == int(pid)


@pytest.mark.integration
@needs_systemd
def test_job_without_scope_is_killed_with_host(tmp_path):
    st, _, scope = _run_restart_case(tmp_path, "never")
    assert scope == "False"
    assert st["status"] == "killed", st
    assert "DONE" not in st["output_tail"]
