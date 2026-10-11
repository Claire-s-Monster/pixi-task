"""Subprocess helper that kills the whole process group on timeout."""

import contextlib
import os
import signal
import subprocess
from collections.abc import Mapping, Sequence

KILL_GRACE_SECONDS = 5.0


def _signal_group(pid: int, sig: int) -> None:
    """Send sig to the process group led by pid; ignore an already-gone group."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


def run_with_group_kill(
    command: Sequence[str],
    *,
    timeout: float,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Like ``subprocess.run(capture_output=True, text=True, timeout=...)``.

    The child leads its own session/process group. On timeout the whole group
    gets SIGTERM, then SIGKILL after a grace period, so grandchildren do not
    outlive the call. ``subprocess.TimeoutExpired`` is raised afterwards,
    exactly as ``subprocess.run`` would.
    """
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
        start_new_session=True,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _signal_group(proc.pid, signal.SIGTERM)
            try:
                proc.communicate(timeout=KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            # Always SIGKILL the group: the direct child may have exited on
            # SIGTERM while grandchildren ignore it.
            _signal_group(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise subprocess.TimeoutExpired(command, timeout) from exc
        except BaseException:
            _signal_group(proc.pid, signal.SIGKILL)
            raise
        return subprocess.CompletedProcess(
            list(command), proc.returncode, stdout, stderr
        )
