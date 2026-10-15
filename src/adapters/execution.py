"""
Pixi execution adapter for secure task and command execution.
"""

import json
import os
import re
import subprocess
import tempfile
import time
from typing import Any

from core.models import (
    CONFLICTING_PIXI_ENV_VARS,
    PixiExecutionContext,
    PixiTaskResult,
)
from core.ports import PixiExecutorPort, LoggingPort, ValidationPort, EnvironmentPort
from core.process import run_with_group_kill
from adapters.background import BackgroundJobManager
from adapters.git_snapshot import changed_since, current_head, is_git_work_tree, take_snapshot


MAX_SEARCH_LIMIT = 50
MAX_SEARCH_MATCHES = 25
STDERR_TAIL_LINES = 20
_PLATFORM_RE = re.compile(r"noarch|[a-z0-9]+-[a-z0-9_]+")


def _check_option_value(label: str, value: str) -> None:
    """Reject values that pixi could parse as a flag or that embed control characters."""
    if not isinstance(value, str) or not value or value.startswith("-"):
        raise ValueError(f"Invalid {label}: {value!r}")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"Invalid {label}: {value!r}")


def _tail(text: str, lines: int = STDERR_TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


def _flatten_search(payload: Any) -> list[dict[str, Any]]:
    """Flatten ``{subdir: [record, ...]}`` into one record list."""
    return [rec for records in payload.values() for rec in records]


def _limit_versions(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Keep the newest ``limit`` records per (subdir, name); stable subdir/name order.

    ``pixi search --json`` cannot be combined with ``--limit``, so it is applied here.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rec in records:
        groups.setdefault((str(rec.get("subdir")), str(rec.get("name"))), []).append(rec)
    limited: list[dict[str, Any]] = []
    for key in sorted(groups):
        newest_first = sorted(groups[key], key=lambda r: r.get("timestamp") or 0, reverse=True)
        limited.extend(newest_first[:limit])
    return limited


class PixiExecutionAdapter(PixiExecutorPort):
    """Adapter for executing pixi tasks and commands securely."""

    def __init__(
        self,
        environment: EnvironmentPort,
        logging: LoggingPort,
        validation: ValidationPort,
        job_manager: BackgroundJobManager | None = None,
    ):
        self.environment = environment
        self.logging = logging
        self.validation = validation
        self.jobs = job_manager or BackgroundJobManager()

    def run_task(
        self, task_name: str, args: list[str], context: PixiExecutionContext
    ) -> PixiTaskResult:
        """Execute a pixi task with arguments."""
        start_time = time.time()

        try:
            # Validate task name
            if not self.validation.validate_task_name(task_name):
                return PixiTaskResult.create_failure(
                    task_name=task_name,
                    stdout="",
                    stderr=f"Invalid task name: {task_name}",
                    exit_code=1,
                    execution_time=time.time() - start_time,
                    working_dir=context.working_dir,
                    command_line=f"pixi run {task_name}",
                )

            # Validate and sanitize arguments
            safe_args = self.validation.validate_arguments(args)

            # Build command
            command = [context.pixi_executable, "run"]
            if context.manifest_path:
                command.extend(["--manifest-path", context.manifest_path])
            if context.environment:
                command.extend(["--environment", context.environment])
            command.append(task_name)
            command.extend(safe_args)
            command_line = " ".join(command)

            # Execute with timeout
            stdout, stderr, exit_code, execution_time = self._execute_with_timeout(
                command=command,
                timeout_seconds=context.timeout,
                working_dir=context.working_dir,
                env=context.get_full_env(),
            )

            # Create result
            if exit_code == 0:
                return PixiTaskResult.create_success(
                    task_name=task_name,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time=execution_time,
                    working_dir=context.working_dir,
                    command_line=command_line,
                    environment=context.environment_vars,
                )
            else:
                return PixiTaskResult.create_failure(
                    task_name=task_name,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    execution_time=execution_time,
                    working_dir=context.working_dir,
                    command_line=command_line,
                    environment=context.environment_vars,
                )

        except Exception as e:
            execution_time = time.time() - start_time
            self.logging.log_error(
                f"Task execution failed: {str(e)}",
                {
                    "task_name": task_name,
                    "args": args,
                    "working_dir": context.working_dir,
                },
            )

            return PixiTaskResult.create_failure(
                task_name=task_name,
                stdout="",
                stderr=f"Execution error: {str(e)}",
                exit_code=1,
                execution_time=execution_time,
                working_dir=context.working_dir,
                command_line=f"pixi run {task_name} {' '.join(args)}",
            )

    def execute_command(self, command: list[str], context: PixiExecutionContext) -> PixiTaskResult:
        """Execute arbitrary command in pixi environment."""
        start_time = time.time()

        try:
            # Build pixi exec command
            pixi_command = [context.pixi_executable, "exec"] + command
            command_line = " ".join(pixi_command)

            # Execute with timeout
            stdout, stderr, exit_code, execution_time = self._execute_with_timeout(
                command=pixi_command,
                timeout_seconds=context.timeout,
                working_dir=context.working_dir,
                env=context.get_full_env(),
            )

            # Create result with command as task name
            task_name = f"exec:{command[0]}" if command else "exec"

            if exit_code == 0:
                return PixiTaskResult.create_success(
                    task_name=task_name,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time=execution_time,
                    working_dir=context.working_dir,
                    command_line=command_line,
                    environment=context.environment_vars,
                )
            else:
                return PixiTaskResult.create_failure(
                    task_name=task_name,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    execution_time=execution_time,
                    working_dir=context.working_dir,
                    command_line=command_line,
                    environment=context.environment_vars,
                )

        except Exception as e:
            execution_time = time.time() - start_time
            self.logging.log_error(
                f"Command execution failed: {str(e)}",
                {"command": command, "working_dir": context.working_dir},
            )

            return PixiTaskResult.create_failure(
                task_name=f"exec:{command[0]}" if command else "exec",
                stdout="",
                stderr=f"Execution error: {str(e)}",
                exit_code=1,
                execution_time=execution_time,
                working_dir=context.working_dir,
                command_line=" ".join(command),
            )

    def install(self, context: PixiExecutionContext) -> PixiTaskResult:
        """Install/sync pixi environment and dependencies."""
        start_time = time.time()

        try:
            # Build install command
            command = [context.pixi_executable, "install"]
            if context.environment:
                command.extend(["--environment", context.environment])
            command_line = " ".join(command)

            # Execute with timeout (longer timeout for installs)
            install_timeout = max(context.timeout, 600)  # At least 10 minutes
            stdout, stderr, exit_code, execution_time = self._execute_with_timeout(
                command=command,
                timeout_seconds=install_timeout,
                working_dir=context.working_dir,
                env=context.get_full_env(),
            )

            if exit_code == 0:
                return PixiTaskResult.create_success(
                    task_name="install",
                    stdout=stdout,
                    stderr=stderr,
                    execution_time=execution_time,
                    working_dir=context.working_dir,
                    command_line=command_line,
                    environment=context.environment_vars,
                )
            else:
                return PixiTaskResult.create_failure(
                    task_name="install",
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    execution_time=execution_time,
                    working_dir=context.working_dir,
                    command_line=command_line,
                    environment=context.environment_vars,
                )

        except Exception as e:
            execution_time = time.time() - start_time
            self.logging.log_error(
                f"Install failed: {str(e)}", {"working_dir": context.working_dir}
            )

            return PixiTaskResult.create_failure(
                task_name="install",
                stdout="",
                stderr=f"Install error: {str(e)}",
                exit_code=1,
                execution_time=execution_time,
                working_dir=context.working_dir,
                command_line="pixi install",
            )

    def run_task_background(
        self,
        task_name: str,
        args: list[str],
        context: PixiExecutionContext,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Launch a pixi task in a detached background process (issue #4)."""
        if not self.validation.validate_task_name(task_name):
            return {
                "status": "error",
                "task_name": task_name,
                "error": f"Invalid task name: {task_name}",
            }

        safe_args = self.validation.validate_arguments(args)

        command = [context.pixi_executable, "run"]
        if context.manifest_path:
            command.extend(["--manifest-path", context.manifest_path])
        if context.environment:
            command.extend(["--environment", context.environment])
        command.append(task_name)
        command.extend(safe_args)
        command_line = " ".join(command)

        self.logging.log_info(
            "Launching background pixi task",
            {
                "task_name": task_name,
                "command": command_line,
                "working_dir": context.working_dir,
            },
        )

        return self.jobs.launch(
            command=command,
            working_dir=context.working_dir,
            env=context.get_full_env(),
            task_name=task_name,
            command_line=command_line,
            output_file=output_file,
        )

    def _build_exec_command(
        self,
        tool: str,
        args: list[str],
        specs: list[str],
        channels: list[str],
        context: PixiExecutionContext,
    ) -> list[str]:
        """Build ``pixi exec [--with S]... [-c C]... <tool> <args>...`` (shell=False argv)."""
        for spec in specs:
            _check_option_value("spec", spec)
        for channel in channels:
            _check_option_value("channel", channel)
        for arg in args:
            if not isinstance(arg, str) or "\x00" in arg:
                raise ValueError(f"Invalid argument for pixi_exec: {arg!r}")

        command = [context.pixi_executable, "exec"]
        for spec in specs:
            command.extend(["--with", spec])
        for channel in channels:
            command.extend(["-c", channel])
        command.append(tool)
        command.extend(args)
        return command

    def exec_tool(
        self,
        tool: str,
        args: list[str],
        specs: list[str],
        channels: list[str],
        context: PixiExecutionContext,
    ) -> PixiTaskResult:
        """Run ``tool`` via ``pixi exec`` and wait for it; non-zero exit is data."""
        command = self._build_exec_command(tool, args, specs, channels, context)
        command_line = " ".join(command)
        stdout, stderr, exit_code, execution_time = self._execute_with_timeout(
            command=command,
            timeout_seconds=context.timeout,
            working_dir=context.working_dir,
            env=context.get_full_env(),
        )
        if exit_code == 0:
            return PixiTaskResult.create_success(
                task_name=f"exec:{tool}",
                stdout=stdout,
                stderr=stderr,
                execution_time=execution_time,
                working_dir=context.working_dir,
                command_line=command_line,
                environment=context.environment_vars,
            )
        return PixiTaskResult.create_failure(
            task_name=f"exec:{tool}",
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            execution_time=execution_time,
            working_dir=context.working_dir,
            command_line=command_line,
            environment=context.environment_vars,
        )

    def exec_tool_background(
        self,
        tool: str,
        args: list[str],
        specs: list[str],
        channels: list[str],
        context: PixiExecutionContext,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Launch ``pixi exec <tool>`` detached; poll with pixi_task_status / pixi_wait."""
        command = self._build_exec_command(tool, args, specs, channels, context)
        command_line = " ".join(command)
        self.logging.log_info(
            "Launching background pixi exec",
            {"tool": tool, "command": command_line, "working_dir": context.working_dir},
        )
        return self.jobs.launch(
            command=command,
            working_dir=context.working_dir,
            env=context.get_full_env(),
            task_name=f"exec:{tool}",
            command_line=command_line,
            output_file=output_file,
        )

    def run_pixi_exec(self, argv_tail: list[str], context: PixiExecutionContext) -> PixiTaskResult:
        """Run ``pixi exec <argv_tail...>`` and wait; a non-zero exit is returned as data.

        Used by the dedicated conda-smithy tools. These invoke the fixed tool
        directly and are deliberately NOT subject to the pixi_exec allowlist:
        each dedicated tool is its own permission.
        """
        command = [context.pixi_executable, "exec", *argv_tail]
        task_name = f"exec:{argv_tail[0]}" if argv_tail else "exec"
        stdout, stderr, exit_code, execution_time = self._execute_with_timeout(
            command=command,
            timeout_seconds=context.timeout,
            working_dir=context.working_dir,
            env=context.get_full_env(),
        )
        common: dict[str, Any] = {
            "task_name": task_name,
            "stdout": stdout,
            "stderr": stderr,
            "execution_time": execution_time,
            "working_dir": context.working_dir,
            "command_line": " ".join(command),
            "environment": context.environment_vars,
        }
        if exit_code == 0:
            return PixiTaskResult.create_success(**common)
        return PixiTaskResult.create_failure(exit_code=exit_code, **common)

    def launch_pixi_exec_background(
        self,
        argv_tail: list[str],
        context: PixiExecutionContext,
        task_name: str,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Launch ``pixi exec <argv_tail...>`` detached (see run_pixi_exec for the allowlist note)."""
        command = [context.pixi_executable, "exec", *argv_tail]
        command_line = " ".join(command)
        self.logging.log_info(
            "Launching background pixi exec",
            {"task_name": task_name, "command": command_line, "working_dir": context.working_dir},
        )
        return self.jobs.launch(
            command=command,
            working_dir=context.working_dir,
            env=context.get_full_env(),
            task_name=task_name,
            command_line=command_line,
            output_file=output_file,
        )

    def write_job_artifact(self, job_id: str, name: str, data: dict[str, Any]) -> None:
        """Persist a JSON artifact in the job's directory."""
        self.jobs.write_job_artifact(job_id, name, data)

    def read_job_artifact(self, job_id: str, name: str) -> dict[str, Any] | None:
        """Read a JSON artifact from the job's directory (None if absent)."""
        return self.jobs.read_job_artifact(job_id, name)

    def git_is_work_tree(self, repo: str) -> bool:
        """Delegate to adapters.git_snapshot.is_git_work_tree."""
        return is_git_work_tree(repo)

    def git_snapshot(self, repo: str) -> dict[str, Any]:
        """Delegate to adapters.git_snapshot.take_snapshot."""
        return take_snapshot(repo)

    def git_changed_since(self, repo: str, before: dict[str, Any]) -> list[str]:
        """Delegate to adapters.git_snapshot.changed_since."""
        return changed_since(repo, before)

    def git_head(self, repo: str) -> str | None:
        """Delegate to adapters.git_snapshot.current_head."""
        return current_head(repo)

    def search_packages(
        self,
        spec: str,
        channels: list[str],
        platform: str | None,
        limit: int,
        context: PixiExecutionContext,
    ) -> dict[str, Any]:
        """Run ``pixi search --json`` from a throwaway cwd and summarise the matches."""
        _check_option_value("spec", spec)
        for channel in channels:
            _check_option_value("channel", channel)
        if platform is not None and not _PLATFORM_RE.fullmatch(platform):
            raise ValueError(f"Invalid platform: {platform!r}")
        if not 1 <= limit <= MAX_SEARCH_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}, got {limit}")

        command = [context.pixi_executable, "search", "--json"]
        for channel in channels:
            command.extend(["-c", channel])
        if platform is not None:
            command.extend(["-p", platform])
        command.append(spec)

        # Without -p pixi consults the cwd's manifest; a fresh empty directory
        # keeps results independent of whatever project the server runs in.
        with tempfile.TemporaryDirectory() as empty_dir:
            stdout, stderr, exit_code, _ = self._execute_with_timeout(
                command=command,
                timeout_seconds=context.timeout,
                working_dir=empty_dir,
                env=context.get_full_env(),
            )

        base = {"spec": spec, "channels": list(channels), "platform": platform}
        if exit_code != 0:
            if "No packages found" in stderr:
                return {
                    "found": False,
                    **base,
                    "matches": [],
                    "total_matches": 0,
                    "truncated": False,
                }
            raise RuntimeError(f"pixi search failed (exit {exit_code}): {_tail(stderr)}")

        try:
            records = _limit_versions(_flatten_search(json.loads(stdout)), limit)
        except (ValueError, AttributeError, TypeError) as e:
            raise RuntimeError(
                f"pixi search returned unparseable output ({e}): {_tail(stderr)}"
            ) from e

        matches = [
            {key: rec.get(key) for key in ("name", "version", "build", "subdir", "channel")}
            for rec in records[:MAX_SEARCH_MATCHES]
        ]
        return {
            "found": bool(records),
            **base,
            "matches": matches,
            "total_matches": len(records),
            "truncated": len(records) > MAX_SEARCH_MATCHES,
        }

    def get_job_status(self, job_id: str, tail_lines: int = 50) -> dict[str, Any]:
        """Return the status and output tail of a background job."""
        return self.jobs.status(job_id, tail_lines)

    def wait_for_job(
        self,
        job_id: str,
        wait_s: float = 15,
        result_contains: list[str] | None = None,
        max_result_lines: int = 25,
    ) -> dict[str, Any]:
        """Bounded long-poll on a background job (see BackgroundJobManager.wait)."""
        return self.jobs.wait(job_id, wait_s, result_contains, max_result_lines)

    def check_pixi_available(self) -> bool:
        """Check if pixi executable is available."""
        try:
            result = subprocess.run(
                ["pixi", "--version"], capture_output=True, timeout=10, text=True
            )
            return result.returncode == 0
        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            FileNotFoundError,
        ):
            return False

    def _execute_with_timeout(
        self,
        command: list[str],
        timeout_seconds: int,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, int, float]:
        """Execute a command with timeout and return (stdout, stderr, exit_code, execution_time)."""
        start_time = time.time()

        try:
            # The caller (get_full_env) already supplies a complete, sanitized
            # environment. Re-copying os.environ here would re-introduce the
            # pixi activation vars stripped upstream (issue #6), so only fall
            # back to a (sanitized) os.environ copy when no env is provided.
            if env is not None:
                full_env = env
            else:
                full_env = os.environ.copy()
                for var in CONFLICTING_PIXI_ENV_VARS:
                    full_env.pop(var, None)

            # Execute command
            result = run_with_group_kill(
                command,
                timeout=timeout_seconds,
                cwd=working_dir,
                env=full_env,
            )

            execution_time = time.time() - start_time

            self.logging.log_info(
                "Command executed",
                {
                    "command": " ".join(command),
                    "exit_code": result.returncode,
                    "execution_time": execution_time,
                    "working_dir": working_dir,
                },
            )

            return result.stdout, result.stderr, result.returncode, execution_time

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            error_msg = f"Command timed out after {timeout_seconds} seconds"

            self.logging.log_error(
                error_msg,
                {
                    "command": " ".join(command),
                    "timeout": timeout_seconds,
                    "execution_time": execution_time,
                },
            )

            return "", error_msg, 124, execution_time  # 124 is timeout exit code

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Command execution failed: {str(e)}"

            self.logging.log_error(
                error_msg,
                {
                    "command": " ".join(command),
                    "error": str(e),
                    "execution_time": execution_time,
                },
            )

            return "", error_msg, 1, execution_time
