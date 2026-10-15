"""
Background job execution for long-running pixi tasks.

This module solves the MCP-transport timeout problem (issue #4): pixi
environment activation plus a large pytest suite can exceed the transport
window before any output is produced, dropping the connection. Background
mode launches the task in a detached child process whose stdout/stderr stream
to a per-job log file, returns a job handle immediately, and lets the caller
poll for completion or read the log file directly.

Design notes:
- The child is spawned with ``start_new_session=True`` so it survives the MCP
  request returning (and is not killed when the request handler unwinds).
- A per-job directory under the system temp dir holds ``output.log`` and
  ``status.json``. The status file is written by a daemon waiter thread when
  the child exits, so completion state survives a server restart.
- ``status()`` prefers the live process handle (``poll()``), then falls back to
  the on-disk ``status.json``, then to PID liveness. This keeps status reporting
  correct whether or not the original launching process is still alive.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# pixi_wait limits (issue #31). MAX_WAIT_S stays below typical MCP transport
# windows so a single call never outlives the client's patience.
MAX_WAIT_S = 15.0
WAIT_POLL_INTERVAL_S = 0.5
MAX_CONCURRENT_WAITS = 8
MAX_RESULT_CONTAINS_ITEMS = 10
MAX_RESULT_CONTAINS_LEN = 256
MAX_RESULT_LINES_CAP = 100
TAIL_BYTES = 8192


# launch() generates job ids as uuid4().hex[:12]; anything else is never a real
# job and must not be used as a path component.
_JOB_ID_RE = re.compile(r"[0-9a-f]{12}")
_ARTIFACT_NAME_RE = re.compile(r"[a-z0-9_]+\.json")


SCOPE_ENV = "PIXI_TASK_JOB_SCOPE"
SCOPE_PROBE_S = 0.5
KILLED_MESSAGE = (
    "process ended without recording an exit code (killed: e.g. a pixi-task "
    "restart without scope isolation, or SIGKILL)"
)
_EXIT_WRAPPER = 'rc=0; "$@" || rc=$?; printf "%s" "$rc" > "$0.tmp" && mv "$0.tmp" "$0"; exit "$rc"'


def _is_valid_job_id(job_id: object) -> bool:
    return isinstance(job_id, str) and _JOB_ID_RE.fullmatch(job_id) is not None


def should_use_scope(mode: str, systemd_run_available: bool, in_systemd_unit: bool) -> bool:
    """Decide whether to launch a job in its own systemd scope.

    ``never`` disables, ``always`` needs only systemd-run, anything else is
    ``auto``: systemd-run present and we are running inside a systemd unit.
    """
    if mode == "never" or not systemd_run_available:
        return False
    return mode == "always" or in_systemd_unit


def wrap_command(command: list[str], exit_path: Path) -> list[str]:
    """Wrap ``command`` so the shell itself records the exit code in ``exit_path``.

    ``$0`` is the exit file and ``$@`` the untouched original argv, so arguments
    with spaces or quotes are never re-parsed by the shell.
    """
    return ["/bin/sh", "-c", _EXIT_WRAPPER, str(exit_path), *command]


def _proc_stat(pid: int) -> tuple[str, str] | None:
    """(state, start_time_ticks) from /proc/<pid>/stat, or None if unreadable."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    fields = raw.rpartition(")")[2].split()
    if len(fields) < 20:
        return None
    return fields[0], fields[19]  # fields 3 (state) and 22 (starttime)


def proc_start_time(pid: int) -> str | None:
    """Process start time (clock ticks since boot) used to guard against PID reuse."""
    stat = _proc_stat(pid)
    return stat[1] if stat else None


def _executable_found(program: str, working_dir: str | None, env: dict[str, str] | None) -> bool:
    if "/" in program:
        return os.access(Path(working_dir or ".") / program, os.X_OK)
    return shutil.which(program, path=(env or os.environ).get("PATH")) is not None


def _read_exit_code(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _wait_error(job_id: str, message: str, started: float) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "state": "error",
        "job_status": None,
        "exit_code": None,
        "elapsed_s": time.monotonic() - started,
        "matched_lines": [],
        "output_file": None,
        "error": message,
        "returned_because": "error",
    }


def _validate_needles(needles: list[str]) -> str | None:
    """Return an error message if ``needles`` violate count/length/non-empty limits."""
    if len(needles) > MAX_RESULT_CONTAINS_ITEMS:
        return f"result_contains exceeds {MAX_RESULT_CONTAINS_ITEMS} items"
    if any(not isinstance(n, str) or not n for n in needles):
        return "result_contains items must be non-empty strings"
    if any(len(n) > MAX_RESULT_CONTAINS_LEN for n in needles):
        return f"result_contains item exceeds {MAX_RESULT_CONTAINS_LEN} chars"
    return None


class BackgroundJobManager:
    """Launch and track detached pixi task executions.

    A single manager instance owns an in-memory registry of jobs it launched
    plus a base directory on disk. Each job gets ``<base>/<job_id>/`` holding
    ``output.log`` (combined stdout+stderr) and ``status.json`` (terminal
    state). The on-disk files make a job's result readable even after the
    launching process is gone.
    """

    def __init__(self, base_dir: str | None = None):
        self._base = Path(base_dir) if base_dir else Path(tempfile.gettempdir()) / "pixi-task-jobs"
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._wait_slots = threading.BoundedSemaphore(MAX_CONCURRENT_WAITS)

    def launch(
        self,
        command: list[str],
        working_dir: str | None,
        env: dict[str, str] | None,
        task_name: str,
        command_line: str,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Spawn ``command`` detached and return a job handle immediately.

        Returns a dict with ``status="running"`` plus ``job_id``, ``pid``,
        ``output_file`` and ``status_file`` paths, or ``status="error"`` if the
        process could not be started.
        """
        job_id = uuid.uuid4().hex[:12]
        job_dir = self._base / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        out_path = Path(output_file) if output_file else job_dir / "output.log"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        status_path = job_dir / "status.json"

        started_at = datetime.now(UTC).isoformat()
        start_time = time.time()

        try:
            out_fh = open(out_path, "w")
        except OSError as exc:
            return {
                "status": "error",
                "job_id": job_id,
                "task_name": task_name,
                "error": f"Could not open output file {out_path}: {exc}",
            }

        # The shell wrapper would turn a missing executable into exit 127, so
        # keep reporting it as a launch error up front.
        if not _executable_found(command[0], working_dir, env):
            out_fh.close()
            return {
                "status": "error",
                "job_id": job_id,
                "task_name": task_name,
                "command_line": command_line,
                "error": (
                    "Failed to launch background task: "
                    f"[Errno 2] No such file or directory: {command[0]!r}"
                ),
            }

        exit_path = job_dir / "exit_code"
        wrapped = wrap_command(command, exit_path)
        use_scope = should_use_scope(
            os.environ.get(SCOPE_ENV, "auto"),
            shutil.which("systemd-run") is not None,
            "INVOCATION_ID" in os.environ,
        )
        scope_error: str | None = None

        try:
            if use_scope:
                proc = self._spawn(
                    self._scope_argv(job_id, wrapped), out_fh, working_dir, env, True
                )
                scope_error = self._scope_launch_error(proc, out_path, exit_path)
                if scope_error is not None:
                    use_scope = False
                    out_fh.close()
                    out_fh = open(out_path, "w")
                    proc = self._spawn(wrapped, out_fh, working_dir, env, False)
            else:
                proc = self._spawn(wrapped, out_fh, working_dir, env, False)
        except (OSError, ValueError) as exc:
            out_fh.close()
            return {
                "status": "error",
                "job_id": job_id,
                "task_name": task_name,
                "command_line": command_line,
                "error": f"Failed to launch background task: {exc}",
            }

        pid_start = proc_start_time(proc.pid)
        record = {
            "job_id": job_id,
            "proc": proc,
            "pid": proc.pid,
            "pid_start": pid_start,
            "scope": use_scope,
            "exit_path": str(exit_path),
            "output_file": str(out_path),
            "status_file": str(status_path),
            "task_name": task_name,
            "command_line": command_line,
            "working_dir": working_dir or os.getcwd(),
            "started_at": started_at,
            "start_time": start_time,
            "finished_at": None,
            "exit_code": None,
        }

        # Persist the initial running state so a fresh process can discover the
        # job from disk even before it completes.
        self._write_status(
            status_path,
            {
                "status": "running",
                "job_id": job_id,
                "pid": proc.pid,
                "pid_start": pid_start,
                "scope": use_scope,
                "scope_error": scope_error,
                "task_name": task_name,
                "command_line": command_line,
                "working_dir": record["working_dir"],
                "output_file": str(out_path),
                "started_at": started_at,
                "exit_code": None,
                "finished_at": None,
                "execution_time": None,
            },
        )

        thread = threading.Thread(
            target=self._wait_and_record,
            args=(record, out_fh),
            daemon=True,
        )
        record["thread"] = thread
        with self._lock:
            self._jobs[job_id] = record
        thread.start()

        return {
            "status": "running",
            "job_id": job_id,
            "pid": proc.pid,
            "task_name": task_name,
            "command_line": command_line,
            "working_dir": record["working_dir"],
            "output_file": str(out_path),
            "status_file": str(status_path),
            "started_at": started_at,
            "scope": use_scope,
            "scope_error": scope_error,
            "message": (
                "Task launched in background. Poll pixi_task_status(job_id) for "
                "completion, or read output_file directly."
            ),
        }

    @staticmethod
    def _scope_argv(job_id: str, wrapped: list[str]) -> list[str]:
        return [
            "systemd-run",
            "--user",
            "--scope",
            "--quiet",
            "--collect",
            f"--unit=pixi-task-job-{job_id}",
            "--",
            *wrapped,
        ]

    @staticmethod
    def _spawn(
        argv: list[str],
        out_fh: Any,
        working_dir: str | None,
        env: dict[str, str] | None,
        scoped: bool,
    ) -> subprocess.Popen[str]:
        if scoped and env is not None:
            # systemd-run --user needs the caller's bus location.
            env = dict(env)
            for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
                if key in os.environ:
                    env.setdefault(key, os.environ[key])
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=out_fh,
            stderr=subprocess.STDOUT,
            cwd=working_dir,
            env=env,
            text=True,
            start_new_session=True,
        )

    @staticmethod
    def _scope_launch_error(proc: Any, out_path: Path, exit_path: Path) -> str | None:
        """Detect a systemd-run that failed to start the job (no scope, no bus...).

        Only a fast non-zero exit with no exit file (the wrapper never ran) and
        systemd-style output counts, so a job that ran and failed is never re-run.
        """
        try:
            rc = proc.wait(timeout=SCOPE_PROBE_S)
        except subprocess.TimeoutExpired:
            return None
        if rc == 0 or exit_path.exists():
            return None
        try:
            text = out_path.read_text(errors="replace")
        except OSError:
            return None
        if "Failed to" in text or "bus" in text:
            return text.strip()[:300] or f"systemd-run exited {rc}"
        return None

    def wait(
        self,
        job_id: str,
        wait_s: float = MAX_WAIT_S,
        result_contains: list[str] | None = None,
        max_result_lines: int = 25,
    ) -> dict[str, Any]:
        """Block (bounded) until the job leaves ``running``, or ``wait_s`` elapses.

        Polls the same ``status()`` code path as ``pixi_task_status``. Runs in a
        worker thread (tool calls are dispatched via ``asyncio.to_thread``), so
        ``time.sleep`` here does not block the event loop. Never raises.
        """
        started = time.monotonic()
        try:
            wait_s = float(wait_s)
        except (TypeError, ValueError):
            return _wait_error(job_id, "wait_s must be a finite number", started)
        if not math.isfinite(wait_s):
            return _wait_error(job_id, "wait_s must be a finite number", started)
        needles = list(result_contains or [])
        problem = _validate_needles(needles)
        if problem:
            return _wait_error(job_id, problem, started)
        if not _is_valid_job_id(job_id):
            return _wait_error(job_id, f"No background job found with id '{job_id}'.", started)
        wait_s = min(max(wait_s, 0.0), MAX_WAIT_S)
        limit = min(max(int(max_result_lines), 1), MAX_RESULT_LINES_CAP)

        if not self._wait_slots.acquire(blocking=False):
            return self._wait_check(job_id, started, needles, limit, cap=True)
        try:
            deadline = started + wait_s
            while True:
                result = self._wait_check(job_id, started, needles, limit)
                remaining = deadline - time.monotonic()
                if result["state"] != "waiting" or remaining <= 0:
                    return result
                time.sleep(min(WAIT_POLL_INTERVAL_S, remaining))
        finally:
            self._wait_slots.release()

    def _wait_check(
        self,
        job_id: str,
        started: float,
        needles: list[str],
        limit: int,
        cap: bool = False,
    ) -> dict[str, Any]:
        """One non-blocking look at a job, shaped as a pixi_wait result."""
        if not _is_valid_job_id(job_id) or not (self._base / job_id).is_dir():
            return _wait_error(job_id, f"No background job found with id '{job_id}'.", started)
        snap = self.status(job_id, tail_lines=None)
        job_status = snap.get("status")
        if job_status == "unknown" and snap.get("retryable"):
            job_status = "running"  # status file mid-write: not done yet, not an error
        elif job_status == "unknown" and "No background job" in str(snap.get("error", "")):
            return _wait_error(job_id, snap["error"], started)
        state = "waiting" if job_status == "running" else "done"
        output_file = snap.get("output_file")
        matched: list[str] = []
        if state == "done" and needles:
            matched = self._matched_lines(output_file, needles, limit)
        if state == "done":
            because = "completed"
        else:
            because = "concurrency_cap" if cap else "wait_expired"
        return {
            "job_id": job_id,
            "state": state,
            "job_status": job_status,
            "exit_code": snap.get("exit_code"),
            "elapsed_s": time.monotonic() - started,
            "matched_lines": matched,
            "output_file": output_file,
            "error": snap.get("error") if job_status in ("unknown", "killed") else None,
            "returned_because": because,
        }

    @staticmethod
    def _matched_lines(output_file: str | None, needles: list[str], limit: int) -> list[str]:
        """Lines from a bounded tail of the log containing any needle (last ``limit``)."""
        if not output_file:
            return []
        try:
            with open(output_file, "rb") as fh:
                size = fh.seek(0, os.SEEK_END)
                start = max(0, size - TAIL_BYTES)
                fh.seek(start)
                data = fh.read(TAIL_BYTES)
        except OSError:
            return []
        lines = data.decode("utf-8", errors="replace").splitlines()
        if start > 0:
            lines = lines[1:]  # first line of a mid-file window is likely partial
        matched = [ln for ln in lines if any(n in ln for n in needles)]
        return matched[-limit:]

    def status(self, job_id: str, tail_lines: int | None = 50) -> dict[str, Any]:
        """Return the current state of a background job.

        Resolution order: live process handle, then on-disk ``status.json``,
        then PID liveness. Includes a tail of the captured output unless
        ``tail_lines`` is None (used by the pixi_wait poll loop to avoid
        re-reading the log on every poll).
        """
        if not _is_valid_job_id(job_id):
            return {
                "status": "unknown",
                "job_id": job_id,
                "error": f"No background job found with id '{job_id}'.",
            }
        with self._lock:
            record = self._jobs.get(job_id)

        status_path = self._base / job_id / "status.json"

        if record is not None:
            proc = record["proc"]
            returncode = proc.poll()
            if returncode is None:
                return self._running_payload(record, tail_lines)
            # Process has exited; the waiter thread normally records this, but
            # poll() may observe it first. Make status idempotent either way.
            if record.get("exit_code") is None:
                self._finalize(record, returncode)
            return self._completed_payload(record, tail_lines)

        # No in-memory record (e.g. server restarted). Fall back to disk.
        if status_path.exists():
            try:
                disk: dict[str, Any] = json.loads(status_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                return {
                    "status": "unknown",
                    "job_id": job_id,
                    "error": f"Could not read status file: {exc}",
                    "retryable": True,
                }
            output_file = disk.get("output_file")
            disk["output_tail"] = self._read_tail(output_file, tail_lines)
            # status.json still says running but the pid is gone: the launching
            # server died. The job's own exit file tells us how it ended.
            if disk.get("status") == "running" and not self._pid_alive(
                disk.get("pid"), disk.get("pid_start")
            ):
                disk = self._recover_dead_job(status_path, disk) | {
                    "output_tail": disk["output_tail"]
                }
            return disk

        return {
            "status": "unknown",
            "job_id": job_id,
            "error": f"No background job found with id '{job_id}'.",
        }

    # ----- internal helpers -------------------------------------------------

    def _recover_dead_job(self, status_path: Path, disk: dict[str, Any]) -> dict[str, Any]:
        """Resolve a job whose process is gone but whose status.json says running."""
        disk = {k: v for k, v in disk.items() if k != "output_tail"}
        exit_path = status_path.with_name("exit_code")
        rc = _read_exit_code(exit_path)
        if rc is not None:
            finished = exit_path.stat().st_mtime
            try:
                started = datetime.fromisoformat(disk["started_at"]).timestamp()
                execution_time: float | None = max(finished - started, 0.0)
            except (KeyError, TypeError, ValueError):
                execution_time = None
            disk |= {
                "status": "completed",
                "finished_at": datetime.fromtimestamp(finished, UTC).isoformat(),
                "execution_time": execution_time,
                "exit_code": rc,
                "success": rc == 0,
            }
        else:
            disk |= {
                "status": "killed",
                "finished_at": datetime.now(UTC).isoformat(),
                "exit_code": None,
                "success": False,
                "error": KILLED_MESSAGE,
                "retryable": False,
            }
        self._write_status(status_path, disk)
        return disk

    def _wait_and_record(self, record: dict[str, Any], out_fh: Any) -> None:
        """Block on the child, then close the log handle and persist status."""
        proc = record["proc"]
        returncode = proc.wait()
        try:
            out_fh.close()
        except OSError:
            pass
        self._finalize(record, returncode)

    def _finalize(self, record: dict[str, Any], returncode: int) -> None:
        """Record terminal state for a job (idempotent).

        Invariant: ``record["exit_code"] is not None`` implies ``status.json``
        has already been written. The disk write happens under the lock and
        ``exit_code`` is set last, so concurrent finalizers block until it is done.
        """
        with self._lock:
            if record.get("exit_code") is not None:
                return
            file_rc = _read_exit_code(Path(record["exit_path"]))
            if file_rc is not None:
                returncode = file_rc
            finished_at = datetime.now(UTC).isoformat()
            execution_time = time.time() - record["start_time"]
            self._write_status(
                Path(record["status_file"]),
                {
                    "status": "completed",
                    "job_id": record["job_id"],
                    "pid": record["pid"],
                    "pid_start": record["pid_start"],
                    "scope": record["scope"],
                    "task_name": record["task_name"],
                    "command_line": record["command_line"],
                    "working_dir": record["working_dir"],
                    "output_file": record["output_file"],
                    "started_at": record["started_at"],
                    "finished_at": finished_at,
                    "execution_time": execution_time,
                    "exit_code": returncode,
                    "success": returncode == 0,
                },
            )
            record["finished_at"] = finished_at
            record["execution_time"] = execution_time
            record["exit_code"] = returncode

    def _running_payload(self, record: dict[str, Any], tail_lines: int | None) -> dict[str, Any]:
        return {
            "status": "running",
            "job_id": record["job_id"],
            "pid": record["pid"],
            "task_name": record["task_name"],
            "command_line": record["command_line"],
            "working_dir": record["working_dir"],
            "output_file": record["output_file"],
            "started_at": record["started_at"],
            "exit_code": None,
            "success": None,
            "execution_time": time.time() - record["start_time"],
            "output_tail": self._read_tail(record["output_file"], tail_lines),
        }

    def _completed_payload(self, record: dict[str, Any], tail_lines: int | None) -> dict[str, Any]:
        exit_code = record["exit_code"]
        return {
            "status": "completed",
            "job_id": record["job_id"],
            "pid": record["pid"],
            "task_name": record["task_name"],
            "command_line": record["command_line"],
            "working_dir": record["working_dir"],
            "output_file": record["output_file"],
            "started_at": record["started_at"],
            "finished_at": record["finished_at"],
            "execution_time": record.get("execution_time"),
            "exit_code": exit_code,
            "success": exit_code == 0,
            "scope": record["scope"],
            "output_tail": self._read_tail(record["output_file"], tail_lines),
        }

    def _artifact_path(self, job_id: str, name: str) -> Path:
        if not _is_valid_job_id(job_id):
            raise ValueError(f"No background job found with id '{job_id}'.")
        if not _ARTIFACT_NAME_RE.fullmatch(name) or name == "status.json":
            raise ValueError(f"Invalid artifact name: {name!r}")
        return self._base / job_id / name

    def write_job_artifact(self, job_id: str, name: str, data: dict[str, Any]) -> None:
        """Atomically persist a small JSON artifact in the job's directory."""
        path = self._artifact_path(job_id, name)
        if not path.parent.is_dir():
            raise ValueError(f"No background job found with id '{job_id}'.")
        self._atomic_write_json(path, data)

    def read_job_artifact(self, job_id: str, name: str) -> dict[str, Any] | None:
        """Read a JSON artifact written by write_job_artifact; None if absent."""
        path = self._artifact_path(job_id, name)
        try:
            loaded: dict[str, Any] = json.loads(path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read artifact {name} of job {job_id}: {exc}") from exc
        return loaded

    def read_output(self, job_id: str) -> str | None:
        """Full combined output of a job; None for an unknown job or missing log file."""
        if not _is_valid_job_id(job_id):
            return None
        with self._lock:
            record = self._jobs.get(job_id)
        output_file: str | None
        if record is not None:
            output_file = record["output_file"]
        else:
            try:
                disk = json.loads((self._base / job_id / "status.json").read_text())
            except (OSError, json.JSONDecodeError):
                return None
            output_file = disk.get("output_file")
        if not output_file:
            return None
        try:
            return Path(output_file).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        """Write JSON via a temp file in the same dir + os.replace; raises OSError."""
        tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            tmp_path.write_text(json.dumps(payload, indent=2))
            os.replace(tmp_path, path)
        except OSError:
            tmp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _write_status(status_path: Path, payload: dict[str, Any]) -> None:
        """Write status.json atomically (temp file in the same dir + os.replace).

        Readers (status(), pixi_wait) therefore never observe a half-written file.
        """
        try:
            BackgroundJobManager._atomic_write_json(status_path, payload)
        except OSError:
            pass

    @staticmethod
    def _read_tail(output_file: str | None, tail_lines: int | None) -> str:
        if not output_file or tail_lines is None:
            return ""
        try:
            with open(output_file, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return ""
        if tail_lines <= 0:
            return "".join(lines)
        return "".join(lines[-tail_lines:])

    @staticmethod
    def _pid_alive(pid: int | None, pid_start: str | None = None) -> bool:
        """True if ``pid`` is a live, non-zombie process (and the same one, if ``pid_start`` given)."""
        if not pid:
            return False
        stat = _proc_stat(pid)
        if stat is None:
            return False
        state, start = stat
        if state in ("Z", "X"):
            return False
        return pid_start is None or start == pid_start
