"""
Pixi execution adapter for secure task and command execution.
"""

import os
import subprocess
import time

from core.models import (
    PixiExecutionContext,
    PixiTaskResult,
)
from core.ports import PixiExecutorPort, LoggingPort, ValidationPort, EnvironmentPort


class PixiExecutionAdapter(PixiExecutorPort):
    """Adapter for executing pixi tasks and commands securely."""

    def __init__(
        self,
        environment: EnvironmentPort,
        logging: LoggingPort,
        validation: ValidationPort,
    ):
        self.environment = environment
        self.logging = logging
        self.validation = validation

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

    def execute_command(
        self, command: list[str], context: PixiExecutionContext
    ) -> PixiTaskResult:
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
            # Ensure environment includes system environment
            full_env = os.environ.copy()
            if env:
                full_env.update(env)

            # Execute command
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout_seconds,
                text=True,
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
