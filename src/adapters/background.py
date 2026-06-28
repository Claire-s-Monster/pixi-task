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
import os
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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

        try:
            proc = subprocess.Popen(
                command,
                stdout=out_fh,
                stderr=subprocess.STDOUT,
                cwd=working_dir,
                env=env,
                text=True,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            out_fh.close()
            return {
                "status": "error",
                "job_id": job_id,
                "task_name": task_name,
                "command_line": command_line,
                "error": f"Failed to launch background task: {exc}",
            }

        record = {
            "job_id": job_id,
            "proc": proc,
            "pid": proc.pid,
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
            "message": (
                "Task launched in background. Poll pixi_task_status(job_id) for "
                "completion, or read output_file directly."
            ),
        }

    def status(self, job_id: str, tail_lines: int = 50) -> dict[str, Any]:
        """Return the current state of a background job.

        Resolution order: live process handle, then on-disk ``status.json``,
        then PID liveness. Includes a tail of the captured output.
        """
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
                }
            output_file = disk.get("output_file")
            disk["output_tail"] = self._read_tail(output_file, tail_lines) if output_file else ""
            # If the file still says running but the pid is dead, the launching
            # server died mid-job; we can no longer recover the exit code.
            if disk.get("status") == "running" and not self._pid_alive(disk.get("pid")):
                disk["status"] = "unknown"
                disk["error"] = (
                    "Launching server is no longer running and the job did not "
                    "record a final status; exit code is unrecoverable."
                )
            return disk

        return {
            "status": "unknown",
            "job_id": job_id,
            "error": f"No background job found with id '{job_id}'.",
        }

    # ----- internal helpers -------------------------------------------------

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
        """Record terminal state for a job (idempotent)."""
        with self._lock:
            if record.get("exit_code") is not None:
                return
            finished_at = datetime.now(UTC).isoformat()
            execution_time = time.time() - record["start_time"]
            record["exit_code"] = returncode
            record["finished_at"] = finished_at
            record["execution_time"] = execution_time
        self._write_status(
            Path(record["status_file"]),
            {
                "status": "completed",
                "job_id": record["job_id"],
                "pid": record["pid"],
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

    def _running_payload(self, record: dict[str, Any], tail_lines: int) -> dict[str, Any]:
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

    def _completed_payload(self, record: dict[str, Any], tail_lines: int) -> dict[str, Any]:
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
            "output_tail": self._read_tail(record["output_file"], tail_lines),
        }

    @staticmethod
    def _write_status(status_path: Path, payload: dict[str, Any]) -> None:
        try:
            status_path.write_text(json.dumps(payload, indent=2))
        except OSError:
            pass

    @staticmethod
    def _read_tail(output_file: str | None, tail_lines: int) -> str:
        if not output_file:
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
    def _pid_alive(pid: int | None) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True
