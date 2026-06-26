"""
Core business logic for Pixi Shell MCP Server.

This module implements the secure pixi task execution service,
providing thread-safe operations with comprehensive validation.
"""

import os
import time
from pathlib import Path
from typing import Any

from core.models import (
    PixiExecutionContext,
)
from core.ports import (
    PixiExecutorPort,
    PixiProjectPort,
    LoggingPort,
    ValidationPort,
)


class PixiShellService:
    """
    Core service for secure pixi task execution.

    Provides thread-safe operations with comprehensive validation,
    environment management, and task execution.
    """

    def __init__(
        self,
        pixi_executor: PixiExecutorPort,
        pixi_project: PixiProjectPort,
        logging: LoggingPort,
        validation: ValidationPort,
        default_working_dir: str | None = None,
    ):
        self.pixi_executor = pixi_executor
        self.pixi_project = pixi_project
        self.logging = logging
        self.validation = validation
        # Base directory used to resolve relative/omitted working_dir values.
        # An MCP server's process CWD is unrelated to the caller's project, so
        # callers pass an absolute working_dir per call. When omitted we fall
        # back to this configured base (the launch --repository), or os.getcwd()
        # when no base was configured. We deliberately do NOT os.chdir at startup.
        self.default_working_dir = default_working_dir

    def _resolve_working_dir(self, working_dir: str | None) -> str:
        """Resolve a caller-supplied working_dir to a usable directory path.

        - ``None``        -> the configured base (default_working_dir) or os.getcwd()
        - absolute path   -> used as-is
        - relative path   -> resolved against the configured base / os.getcwd()

        The server process is never ``chdir``-ed, so relative paths resolve
        against the configured project base rather than the server's install dir.
        """
        base = self.default_working_dir or os.getcwd()
        if working_dir is None:
            return base
        path = Path(working_dir)
        if path.is_absolute():
            return working_dir
        return str(Path(base) / path)

    def run_task(
        self,
        task_name: str,
        args: list[str] | None = None,
        working_dir: str | None = None,
        timeout: int = 300,
        environment: str | None = None,
        manifest_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a pixi task with arguments.

        Returns: {"success": bool, "stdout": str, "stderr": str, "exit_code": int, "execution_time": float}
        """
        start_time = time.time()
        working_dir = self._resolve_working_dir(working_dir)

        try:
            # Determine which directory has the pixi project (manifest_path or working_dir)
            project_dir = (
                str(Path(manifest_path).parent) if manifest_path else working_dir
            )

            # Validate pixi project
            if not self.pixi_project.is_pixi_project(project_dir):
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Directory {project_dir} is not a pixi project (no pixi.toml found)",
                    "exit_code": 1,
                    "execution_time": time.time() - start_time,
                    "task_name": task_name,
                    "working_dir": working_dir,
                }

            # Create execution context
            context = PixiExecutionContext(
                working_dir=working_dir,
                timeout=timeout,
                capture_output=True,
                environment=environment,
                manifest_path=manifest_path,
            )

            # Execute task
            result = self.pixi_executor.run_task(task_name, args or [], context)

            self.logging.log_info(
                f"Pixi task executed: {task_name}",
                {
                    "success": result.success,
                    "exit_code": result.exit_code,
                    "execution_time": result.execution_time,
                    "working_dir": working_dir,
                },
            )

            return {
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "execution_time": result.execution_time,
                "task_name": result.task_name,
                "working_dir": result.working_dir,
                "command_line": result.command_line,
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Task execution failed: {str(e)}"

            self.logging.log_error(
                error_msg,
                {
                    "task_name": task_name,
                    "args": args,
                    "working_dir": working_dir,
                    "error": str(e),
                },
            )

            return {
                "success": False,
                "stdout": "",
                "stderr": error_msg,
                "exit_code": 1,
                "execution_time": execution_time,
                "task_name": task_name,
                "working_dir": working_dir,
            }

    def list_tasks(
        self,
        working_dir: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        """
        List all available pixi tasks with descriptions.

        Returns: {"tasks": {"test": "Run pytest", "lint": "Run ruff", ...}, "environment": ...}
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "tasks": {},
                    "environment": environment,
                    "error": f"Directory {working_dir} is not a pixi project",
                }

            available_tasks = self.pixi_project.get_available_tasks(
                working_dir, environment=environment
            )

            self.logging.log_info(
                "Listed pixi tasks",
                {
                    "task_count": len(available_tasks),
                    "working_dir": working_dir,
                    "environment": environment,
                },
            )

            return {"tasks": available_tasks, "environment": environment}

        except Exception as e:
            error_msg = f"Failed to list tasks: {str(e)}"
            self.logging.log_error(
                error_msg, {"working_dir": working_dir, "error": str(e)}
            )

            return {"tasks": {}, "environment": environment, "error": error_msg}

    def task_exists(
        self,
        task_name: str,
        working_dir: str | None = None,
        environment: str | None = None,
    ) -> bool:
        """
        Check if a pixi task exists.

        Returns: True if task exists, False otherwise
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return False

            available_tasks = self.pixi_project.get_available_tasks(
                working_dir, environment=environment
            )
            return task_name in available_tasks

        except Exception as e:
            self.logging.log_error(
                f"Error checking task existence: {str(e)}",
                {"task_name": task_name, "working_dir": working_dir},
            )
            return False

    def install(
        self,
        working_dir: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        """
        Install/sync pixi environment and dependencies.

        Returns: {"success": bool, "stdout": str, "stderr": str, "execution_time": float, "environment": str | None}
        """
        start_time = time.time()
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Directory {working_dir} is not a pixi project",
                    "execution_time": time.time() - start_time,
                    "environment": environment,
                }

            context = PixiExecutionContext(
                working_dir=working_dir,
                timeout=600,  # Longer timeout for installations
                capture_output=True,
                environment=environment,
            )

            result = self.pixi_executor.install(context)

            self.logging.log_info(
                "Pixi install completed",
                {
                    "success": result.success,
                    "execution_time": result.execution_time,
                    "working_dir": working_dir,
                    "environment": environment,
                },
            )

            return {
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "execution_time": result.execution_time,
                "environment": environment,
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Pixi install failed: {str(e)}"

            self.logging.log_error(
                error_msg, {"working_dir": working_dir, "error": str(e)}
            )

            return {
                "success": False,
                "stdout": "",
                "stderr": error_msg,
                "execution_time": execution_time,
                "environment": environment,
            }

    def get_info(self, working_dir: str | None = None) -> dict[str, Any]:
        """
        Get pixi project information and environment status.

        Returns: Project information including dependencies, tasks, environment status
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "is_pixi_project": False,
                    "error": f"Directory {working_dir} is not a pixi project",
                }

            project_info = self.pixi_project.get_project_info(working_dir)

            return {
                "is_pixi_project": True,
                "project_name": project_info.project_name,
                "project_path": project_info.project_path,
                "python_version": project_info.python_version,
                "environment_path": project_info.environment_path,
                "has_lock_file": project_info.has_lock_file,
                "dependencies": project_info.dependencies,
                "dev_dependencies": project_info.dev_dependencies,
                "available_tasks": project_info.available_tasks,
                "channels": project_info.channels,
                "platforms": project_info.platforms,
                "environment_status": project_info.environment_status,
                "last_updated": project_info.last_updated,
            }

        except Exception as e:
            error_msg = f"Failed to get project info: {str(e)}"
            self.logging.log_error(
                error_msg, {"working_dir": working_dir, "error": str(e)}
            )

            return {"is_pixi_project": False, "error": error_msg}

    def execute_command(
        self,
        command: list[str],
        working_dir: str | None = None,
        capture_output: bool = True,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """
        Execute arbitrary command in pixi environment.

        Returns: Command execution result
        """
        start_time = time.time()
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Directory {working_dir} is not a pixi project",
                    "exit_code": 1,
                    "execution_time": time.time() - start_time,
                }

            context = PixiExecutionContext(
                working_dir=working_dir, timeout=timeout, capture_output=capture_output
            )

            result = self.pixi_executor.execute_command(command, context)

            self.logging.log_info(
                "Pixi command executed",
                {
                    "command": " ".join(command),
                    "success": result.success,
                    "execution_time": result.execution_time,
                    "working_dir": working_dir,
                },
            )

            return {
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "execution_time": result.execution_time,
                "command": " ".join(command),
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Command execution failed: {str(e)}"

            self.logging.log_error(
                error_msg,
                {"command": command, "working_dir": working_dir, "error": str(e)},
            )

            return {
                "success": False,
                "stdout": "",
                "stderr": error_msg,
                "exit_code": 1,
                "execution_time": execution_time,
                "command": " ".join(command),
            }

    def add_dependency(
        self,
        package: str,
        channel: str | None = None,
        is_dev: bool = False,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        """
        Add a dependency to pixi project.

        Returns: Operation result
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "success": False,
                    "message": f"Directory {working_dir} is not a pixi project",
                }

            result = self.pixi_project.add_dependency(
                package, channel, is_dev, working_dir
            )

            self.logging.log_info(
                "Dependency added",
                {
                    "package": package,
                    "channel": channel,
                    "is_dev": is_dev,
                    "success": result.success,
                    "working_dir": working_dir,
                },
            )

            return {
                "success": result.success,
                "message": result.message,
                "data": result.data,
            }

        except Exception as e:
            error_msg = f"Failed to add dependency: {str(e)}"
            self.logging.log_error(
                error_msg,
                {"package": package, "working_dir": working_dir, "error": str(e)},
            )

            return {"success": False, "message": error_msg}

    def remove_dependency(
        self, package: str, is_dev: bool = False, working_dir: str | None = None
    ) -> dict[str, Any]:
        """
        Remove a dependency from pixi project.

        Returns: Operation result
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "success": False,
                    "message": f"Directory {working_dir} is not a pixi project",
                }

            result = self.pixi_project.remove_dependency(package, is_dev, working_dir)

            self.logging.log_info(
                "Dependency removed",
                {
                    "package": package,
                    "is_dev": is_dev,
                    "success": result.success,
                    "working_dir": working_dir,
                },
            )

            return {
                "success": result.success,
                "message": result.message,
                "data": result.data,
            }

        except Exception as e:
            error_msg = f"Failed to remove dependency: {str(e)}"
            self.logging.log_error(
                error_msg,
                {"package": package, "working_dir": working_dir, "error": str(e)},
            )

            return {"success": False, "message": error_msg}

    def list_dependencies(self, working_dir: str | None = None) -> dict[str, Any]:
        """
        List all project dependencies with versions.

        Returns: Dependencies information
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "dependencies": {},
                    "dev_dependencies": {},
                    "error": f"Directory {working_dir} is not a pixi project",
                }

            project_info = self.pixi_project.get_project_info(working_dir)

            return {
                "dependencies": project_info.dependencies,
                "dev_dependencies": project_info.dev_dependencies,
                "channels": project_info.channels,
                "platforms": project_info.platforms,
            }

        except Exception as e:
            error_msg = f"Failed to list dependencies: {str(e)}"
            self.logging.log_error(
                error_msg, {"working_dir": working_dir, "error": str(e)}
            )

            return {"dependencies": {}, "dev_dependencies": {}, "error": error_msg}

    def get_project_status(self, working_dir: str | None = None) -> dict[str, Any]:
        """
        Get comprehensive project status.

        Returns: Project health and status information
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            health_check = self.pixi_project.check_health(working_dir)

            return {
                "is_pixi_project": health_check.is_pixi_project,
                "pixi_executable_found": health_check.pixi_executable_found,
                "environment_exists": health_check.environment_exists,
                "environment_synced": health_check.environment_synced,
                "lock_file_exists": health_check.lock_file_exists,
                "is_healthy": health_check.is_healthy(),
                "issues": health_check.issues,
                "recommendations": health_check.recommendations,
                "checked_at": health_check.checked_at,
            }

        except Exception as e:
            error_msg = f"Failed to get project status: {str(e)}"
            self.logging.log_error(
                error_msg, {"working_dir": working_dir, "error": str(e)}
            )

            return {
                "is_pixi_project": False,
                "is_healthy": False,
                "issues": [error_msg],
                "recommendations": [
                    "Check if pixi is installed and directory contains pixi.toml"
                ],
                "error": error_msg,
            }

    def init_project(self, path: str, template: str | None = None) -> dict[str, Any]:
        """
        Initialize a new pixi project.

        Returns: Initialization result
        """
        try:
            result = self.pixi_project.init_project(path, template)

            self.logging.log_info(
                "Pixi project initialized",
                {"path": path, "template": template, "success": result.success},
            )

            return {
                "success": result.success,
                "message": result.message,
                "project_path": path,
            }

        except Exception as e:
            error_msg = f"Failed to initialize project: {str(e)}"
            self.logging.log_error(
                error_msg, {"path": path, "template": template, "error": str(e)}
            )

            return {"success": False, "message": error_msg, "project_path": path}

    def rattler_build_smart(
        self,
        recipe_path: str = ".",
        target_platform: str | None = None,
        channels: list[str] | None = None,
        variant_config: str | None = None,
        variants: dict[str, str] | None = None,
        working_dir: str | None = None,
        timeout: int = 1800,
    ) -> dict[str, Any]:
        """
        Run rattler-build with smart output summarization.

        Parses build output for errors/warnings and returns structured summary.

        Args:
            recipe_path: Path to recipe.yaml or directory containing it (default: ".")
            target_platform: Target platform for the build (e.g., "linux-64", "osx-arm64")
            channels: List of channels to search for dependencies
            variant_config: Path to variant configuration file
            variants: Dict of variant overrides (e.g., {"python": "3.12"})
            working_dir: Working directory for build
            timeout: Build timeout in seconds (default: 30 minutes)

        Returns: {
            "status": "success" | "failed" | "error",
            "duration": float,
            "errors": list[str],
            "warnings": list[str],
            "packages_built": list[str],
            "output_tail": str,
            "command": str
        }
        """
        import re
        import subprocess

        start_time = time.time()
        working_dir = self._resolve_working_dir(working_dir)

        # Build command
        cmd = ["rattler-build", "build", "-r", recipe_path]

        if target_platform:
            cmd.extend(["--target-platform", target_platform])

        if channels:
            for channel in channels:
                cmd.extend(["-c", channel])

        if variant_config:
            cmd.extend(["-m", variant_config])

        if variants:
            for key, value in variants.items():
                cmd.extend(["--variant", f"{key}={value}"])

        command_str = " ".join(cmd)

        try:
            self.logging.log_info(
                "Starting rattler-build",
                {
                    "recipe_path": recipe_path,
                    "target_platform": target_platform,
                    "channels": channels,
                    "variants": variants,
                    "working_dir": working_dir,
                },
            )

            # Run the build
            result = subprocess.run(
                cmd, cwd=working_dir, capture_output=True, text=True, timeout=timeout
            )

            duration = time.time() - start_time
            output = result.stdout + result.stderr

            # Parse errors and warnings
            errors = []
            warnings = []
            packages_built = []

            # Error patterns
            error_patterns = [
                r"error\[.*?\]:\s*(.+)",
                r"Error:\s*(.+)",
                r"ERROR:\s*(.+)",
                r"fatal:\s*(.+)",
                r"Failed to (.+)",
                r"Could not (.+)",
                r"cannot find (.+)",
                r"undefined reference to (.+)",
            ]

            # Warning patterns
            warning_patterns = [
                r"warning\[.*?\]:\s*(.+)",
                r"Warning:\s*(.+)",
                r"WARN:\s*(.+)",
                r"deprecated:\s*(.+)",
            ]

            # Package built patterns
            package_patterns = [
                r"Successfully built:\s*(.+\.conda)",
                r"Output:\s*(.+\.conda)",
                r"Package built:\s*(.+)",
            ]

            for line in output.split("\n"):
                line = line.strip()
                if not line:
                    continue

                # Check for errors
                for pattern in error_patterns:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        errors.append(line[:200])  # Truncate long lines
                        break

                # Check for warnings
                for pattern in warning_patterns:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        warnings.append(line[:200])
                        break

                # Check for built packages
                for pattern in package_patterns:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        packages_built.append(match.group(1))
                        break

            # Determine status
            if result.returncode == 0:
                status = "success"
            else:
                status = "failed"

            # Get last 50 lines of output for context
            output_lines = output.strip().split("\n")
            output_tail = (
                "\n".join(output_lines[-50:]) if len(output_lines) > 50 else output
            )

            # Deduplicate errors and warnings
            errors = list(dict.fromkeys(errors))[:20]  # Max 20 unique errors
            warnings = list(dict.fromkeys(warnings))[:20]  # Max 20 unique warnings

            self.logging.log_info(
                "rattler-build completed",
                {
                    "status": status,
                    "duration": duration,
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                    "packages_built": packages_built,
                    "exit_code": result.returncode,
                },
            )

            return {
                "status": status,
                "duration": round(duration, 2),
                "exit_code": result.returncode,
                "errors": errors,
                "warnings": warnings,
                "packages_built": packages_built,
                "output_tail": output_tail[:4000],  # Limit output size
                "command": command_str,
                "working_dir": working_dir,
            }

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            error_msg = f"Build timed out after {timeout} seconds"

            self.logging.log_error(
                error_msg,
                {
                    "recipe_path": recipe_path,
                    "timeout": timeout,
                    "working_dir": working_dir,
                },
            )

            return {
                "status": "error",
                "duration": round(duration, 2),
                "exit_code": -1,
                "errors": [error_msg],
                "warnings": [],
                "packages_built": [],
                "output_tail": "",
                "command": command_str,
                "working_dir": working_dir,
            }

        except FileNotFoundError:
            duration = time.time() - start_time
            error_msg = "rattler-build not found. Install with: pixi global install rattler-build"

            self.logging.log_error(
                error_msg, {"recipe_path": recipe_path, "working_dir": working_dir}
            )

            return {
                "status": "error",
                "duration": round(duration, 2),
                "exit_code": -1,
                "errors": [error_msg],
                "warnings": [],
                "packages_built": [],
                "output_tail": "",
                "command": command_str,
                "working_dir": working_dir,
            }

        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Build failed: {str(e)}"

            self.logging.log_error(
                error_msg,
                {
                    "recipe_path": recipe_path,
                    "working_dir": working_dir,
                    "error": str(e),
                },
            )

            return {
                "status": "error",
                "duration": round(duration, 2),
                "exit_code": -1,
                "errors": [error_msg],
                "warnings": [],
                "packages_built": [],
                "output_tail": "",
                "command": command_str,
                "working_dir": working_dir,
            }
