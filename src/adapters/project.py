"""
Pixi project adapter for managing pixi project information and operations.
"""

import os
import subprocess
import time
import toml
from datetime import datetime, timezone
from pathlib import Path

from core.models import (
    PixiHealthCheck,
    PixiOperationResult,
    PixiProjectInfo,
    PixiEnvironmentInfo,
)
from core.ports import PixiProjectPort, LoggingPort, EnvironmentPort


class PixiProjectAdapter(PixiProjectPort):
    """Adapter for pixi project management and information."""

    def __init__(self, environment: EnvironmentPort, logging: LoggingPort):
        self.environment = environment
        self.logging = logging

    def is_pixi_project(self, path: str) -> bool:
        """Check if directory contains a pixi project."""
        try:
            # Check for standalone pixi.toml
            pixi_toml_path = Path(path) / "pixi.toml"
            if pixi_toml_path.exists():
                return True

            # Check for pyproject.toml with [tool.pixi] sections
            pyproject_toml_path = Path(path) / "pyproject.toml"
            if pyproject_toml_path.exists():
                with open(pyproject_toml_path, "r") as f:
                    config = toml.load(f)
                    return "tool" in config and "pixi" in config["tool"]

            return False
        except Exception:
            return False

    def get_project_info(self, path: str) -> PixiProjectInfo:
        """Get comprehensive pixi project information."""
        try:
            if not self.is_pixi_project(path):
                return PixiProjectInfo.create_empty(path)

            # Check for standalone pixi.toml first
            pixi_toml_path = Path(path) / "pixi.toml"
            pyproject_toml_path = Path(path) / "pyproject.toml"

            config = {}
            config_file = ""

            if pixi_toml_path.exists():
                config_file = str(pixi_toml_path)
                try:
                    with open(pixi_toml_path, "r") as f:
                        config = toml.load(f)
                except Exception as e:
                    self.logging.log_error(
                        f"Failed to parse pixi.toml: {str(e)}", {"path": path}
                    )
                    return PixiProjectInfo.create_empty(path)
            elif pyproject_toml_path.exists():
                config_file = str(pyproject_toml_path)
                try:
                    with open(pyproject_toml_path, "r") as f:
                        full_config = toml.load(f)
                        # Extract pixi configuration from [tool.pixi] sections
                        if "tool" in full_config and "pixi" in full_config["tool"]:
                            config = full_config["tool"]["pixi"]
                            # Also get project info from main project section
                            if "project" in full_config:
                                config["project"] = full_config["project"]
                except Exception as e:
                    self.logging.log_error(
                        f"Failed to parse pyproject.toml: {str(e)}", {"path": path}
                    )
                    return PixiProjectInfo.create_empty(path)
            else:
                return PixiProjectInfo.create_empty(path)

            # Extract project information
            project_name = config.get("project", {}).get("name", "")

            # Get dependencies
            dependencies = config.get("dependencies", {})
            dev_dependencies = config.get("dev-dependencies", {})

            # Get tasks
            tasks = config.get("tasks", {})
            available_tasks = {}
            for task_name, task_def in tasks.items():
                if isinstance(task_def, str):
                    available_tasks[task_name] = task_def
                elif isinstance(task_def, dict):
                    available_tasks[task_name] = task_def.get("cmd", "")
                else:
                    available_tasks[task_name] = str(task_def)

            # Get channels and platforms
            channels = config.get("project", {}).get("channels", ["conda-forge"])
            platforms = config.get("project", {}).get("platforms", [])

            # Check for lock file
            lock_file_path = Path(path) / "pixi.lock"
            has_lock_file = lock_file_path.exists()

            # Get environment information
            environment_path = self._get_environment_path(path)
            environment_status = self._get_environment_status(path)

            # Get Python version
            python_version = self._get_python_version(path, config)

            return PixiProjectInfo(
                project_path=path,
                project_name=project_name,
                python_version=python_version,
                environment_path=environment_path,
                has_lock_file=has_lock_file,
                dependencies=dependencies,
                dev_dependencies=dev_dependencies,
                available_tasks=available_tasks,
                channels=channels,
                platforms=platforms,
                environment_status=environment_status,
                last_updated=datetime.now(timezone.utc).isoformat(),
            )

        except Exception as e:
            self.logging.log_error(
                f"Failed to get project info: {str(e)}", {"path": path}
            )
            return PixiProjectInfo.create_empty(path)

    def get_available_tasks(
        self, path: str, environment: str | None = None
    ) -> dict[str, str]:
        """Get available pixi tasks with descriptions."""
        try:
            if not self.is_pixi_project(path):
                return {}

            # Check for standalone pixi.toml first
            pixi_toml_path = Path(path) / "pixi.toml"
            pyproject_toml_path = Path(path) / "pyproject.toml"

            config: dict = {}

            if pixi_toml_path.exists():
                with open(pixi_toml_path, "r") as f:
                    config = toml.load(f)
            elif pyproject_toml_path.exists():
                with open(pyproject_toml_path, "r") as f:
                    full_config = toml.load(f)
                    # Extract pixi configuration from [tool.pixi] sections
                    if "tool" in full_config and "pixi" in full_config["tool"]:
                        config = full_config["tool"]["pixi"]
            else:
                return {}

            # Pixi semantics: env=None unions all features for discovery; specific env walks [environments]
            base_tasks: dict = config.get("tasks", {})
            if environment is None:
                merged: dict = dict(base_tasks)
                for feature_def in config.get("feature", {}).values():
                    merged.update(feature_def.get("tasks", {}))
            elif environment == "default":
                merged = dict(base_tasks)
            else:
                env_entry = config.get("environments", {}).get(environment)
                if env_entry is None:
                    return {}
                if isinstance(env_entry, dict):
                    feature_names: list = env_entry.get("features", [])
                elif isinstance(env_entry, list):
                    feature_names = env_entry
                else:
                    return {}
                merged = dict(base_tasks)
                for fname in feature_names:
                    feature_def = config.get("feature", {}).get(fname, {})
                    merged.update(feature_def.get("tasks", {}))

            available_tasks: dict[str, str] = {}
            for task_name, task_def in merged.items():
                if isinstance(task_def, str):
                    available_tasks[task_name] = task_def
                elif isinstance(task_def, dict):
                    available_tasks[task_name] = task_def.get("cmd", "")
                else:
                    available_tasks[task_name] = str(task_def)

            return available_tasks

        except Exception as e:
            self.logging.log_error(f"Failed to get tasks: {str(e)}", {"path": path})
            return {}

    def add_dependency(
        self,
        package: str,
        channel: str | None = None,
        is_dev: bool = False,
        working_dir: str | None = None,
    ) -> PixiOperationResult:
        """Add a dependency to pixi project."""
        start_time = time.time()
        working_dir = working_dir or os.getcwd()

        try:
            if not self.is_pixi_project(working_dir):
                return PixiOperationResult.error_result(
                    message=f"Not a pixi project: {working_dir}",
                    operation_type="add_dependency",
                    execution_time=time.time() - start_time,
                )

            # Build command
            command = ["pixi", "add"]
            if is_dev:
                command.append("--dev")
            if channel:
                command.extend(["--channel", channel])
            command.append(package)

            # Execute command
            result = subprocess.run(
                command, capture_output=True, text=True, cwd=working_dir, timeout=120
            )

            execution_time = time.time() - start_time

            if result.returncode == 0:
                return PixiOperationResult.success_result(
                    message=f"Successfully added dependency: {package}",
                    operation_type="add_dependency",
                    execution_time=execution_time,
                    data={"package": package, "channel": channel, "is_dev": is_dev},
                )
            else:
                return PixiOperationResult.error_result(
                    message=f"Failed to add dependency: {result.stderr}",
                    operation_type="add_dependency",
                    execution_time=execution_time,
                    error=result.stderr,
                )

        except Exception as e:
            execution_time = time.time() - start_time
            self.logging.log_error(
                f"Add dependency failed: {str(e)}",
                {"package": package, "working_dir": working_dir},
            )

            return PixiOperationResult.error_result(
                message=f"Error adding dependency: {str(e)}",
                operation_type="add_dependency",
                execution_time=execution_time,
                error=str(e),
            )

    def remove_dependency(
        self, package: str, is_dev: bool = False, working_dir: str | None = None
    ) -> PixiOperationResult:
        """Remove a dependency from pixi project."""
        start_time = time.time()
        working_dir = working_dir or os.getcwd()

        try:
            if not self.is_pixi_project(working_dir):
                return PixiOperationResult.error_result(
                    message=f"Not a pixi project: {working_dir}",
                    operation_type="remove_dependency",
                    execution_time=time.time() - start_time,
                )

            # Build command
            command = ["pixi", "remove"]
            if is_dev:
                command.append("--dev")
            command.append(package)

            # Execute command
            result = subprocess.run(
                command, capture_output=True, text=True, cwd=working_dir, timeout=60
            )

            execution_time = time.time() - start_time

            if result.returncode == 0:
                return PixiOperationResult.success_result(
                    message=f"Successfully removed dependency: {package}",
                    operation_type="remove_dependency",
                    execution_time=execution_time,
                    data={"package": package, "is_dev": is_dev},
                )
            else:
                return PixiOperationResult.error_result(
                    message=f"Failed to remove dependency: {result.stderr}",
                    operation_type="remove_dependency",
                    execution_time=execution_time,
                    error=result.stderr,
                )

        except Exception as e:
            execution_time = time.time() - start_time
            self.logging.log_error(
                f"Remove dependency failed: {str(e)}",
                {"package": package, "working_dir": working_dir},
            )

            return PixiOperationResult.error_result(
                message=f"Error removing dependency: {str(e)}",
                operation_type="remove_dependency",
                execution_time=execution_time,
                error=str(e),
            )

    def check_health(self, path: str) -> PixiHealthCheck:
        """Perform comprehensive health check of pixi project."""
        issues = []
        recommendations = []

        try:
            # Check if it's a pixi project
            is_pixi_project = self.is_pixi_project(path)
            if not is_pixi_project:
                issues.append("No pixi.toml file found")
                recommendations.append("Run 'pixi init' to initialize a pixi project")

            # Check if pixi executable is available
            pixi_executable_found = self._check_pixi_executable()
            if not pixi_executable_found:
                issues.append("Pixi executable not found")
                recommendations.append(
                    "Install pixi: curl -fsSL https://pixi.sh/install.sh | bash"
                )

            # Check lock file
            lock_file_exists = False
            if is_pixi_project:
                lock_file_path = Path(path) / "pixi.lock"
                lock_file_exists = lock_file_path.exists()
                if not lock_file_exists:
                    issues.append("No pixi.lock file found")
                    recommendations.append("Run 'pixi install' to create lock file")

            # Check environment
            environment_exists = False
            environment_synced = False
            if is_pixi_project and pixi_executable_found:
                environment_path = self._get_environment_path(path)
                if environment_path:
                    environment_exists = Path(environment_path).exists()

                if environment_exists:
                    # Check if environment is synced
                    environment_synced = self._check_environment_synced(path)
                    if not environment_synced:
                        issues.append("Environment not synchronized with dependencies")
                        recommendations.append("Run 'pixi install' to sync environment")
                else:
                    issues.append("Pixi environment not found")
                    recommendations.append("Run 'pixi install' to create environment")

            if len(issues) == 0:
                return PixiHealthCheck.create_healthy(path)
            else:
                return PixiHealthCheck.create_unhealthy(path, issues, recommendations)

        except Exception as e:
            self.logging.log_error(f"Health check failed: {str(e)}", {"path": path})
            return PixiHealthCheck.create_unhealthy(
                path,
                [f"Health check error: {str(e)}"],
                ["Check project configuration and pixi installation"],
            )

    def init_project(
        self, path: str, template: str | None = None
    ) -> PixiOperationResult:
        """Initialize a new pixi project."""
        start_time = time.time()

        try:
            # Build command
            command = ["pixi", "init"]
            if template:
                command.extend(["--template", template])
            command.append(path)

            # Execute command
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)

            execution_time = time.time() - start_time

            if result.returncode == 0:
                return PixiOperationResult.success_result(
                    message=f"Successfully initialized pixi project at: {path}",
                    operation_type="init_project",
                    execution_time=execution_time,
                    data={"path": path, "template": template},
                )
            else:
                return PixiOperationResult.error_result(
                    message=f"Failed to initialize project: {result.stderr}",
                    operation_type="init_project",
                    execution_time=execution_time,
                    error=result.stderr,
                )

        except Exception as e:
            execution_time = time.time() - start_time
            self.logging.log_error(
                f"Project init failed: {str(e)}", {"path": path, "template": template}
            )

            return PixiOperationResult.error_result(
                message=f"Error initializing project: {str(e)}",
                operation_type="init_project",
                execution_time=execution_time,
                error=str(e),
            )

    def get_environment_info(self, path: str) -> PixiEnvironmentInfo:
        """Get pixi environment information."""
        try:
            if not self.is_pixi_project(path):
                return PixiEnvironmentInfo.create_not_found()

            environment_path = self._get_environment_path(path)
            if not environment_path or not Path(environment_path).exists():
                return PixiEnvironmentInfo.create_not_found()

            # Get Python executable and version
            python_executable = None
            python_version = None

            try:
                python_path = Path(environment_path) / "bin" / "python"
                if python_path.exists():
                    python_executable = str(python_path)

                    # Get Python version
                    result = subprocess.run(
                        [str(python_path), "--version"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        python_version = result.stdout.strip()
            except Exception:
                pass

            # Calculate environment size
            environment_size_mb = 0.0
            try:
                total_size = sum(
                    f.stat().st_size
                    for f in Path(environment_path).rglob("*")
                    if f.is_file()
                )
                environment_size_mb = total_size / (1024 * 1024)
            except Exception:
                pass

            # Count packages (simplified)
            package_count = 0
            try:
                conda_meta_path = Path(environment_path) / "conda-meta"
                if conda_meta_path.exists():
                    package_count = len(list(conda_meta_path.glob("*.json")))
            except Exception:
                pass

            return PixiEnvironmentInfo(
                environment_path=environment_path,
                python_executable=python_executable,
                python_version=python_version,
                is_activated=False,  # Would need more complex check
                package_count=package_count,
                environment_size_mb=environment_size_mb,
            )

        except Exception as e:
            self.logging.log_error(
                f"Failed to get environment info: {str(e)}", {"path": path}
            )
            return PixiEnvironmentInfo.create_not_found()

    def _get_environment_path(self, path: str) -> str | None:
        """Get the path to the pixi environment."""
        try:
            # Try to get environment path from pixi info
            result = subprocess.run(
                ["pixi", "info"], capture_output=True, text=True, cwd=path, timeout=10
            )

            if result.returncode == 0:
                # Parse output to find environment path
                for line in result.stdout.split("\n"):
                    if "Environment" in line and "path" in line.lower():
                        # Extract path from output (implementation depends on pixi info format)
                        pass

            # Fallback: construct standard environment path
            # This is typically in .pixi/envs/default
            project_name = Path(path).name
            env_path = Path(path) / ".pixi" / "envs" / "default"

            if env_path.exists():
                return str(env_path)

        except Exception:
            pass

        return None

    def _get_environment_status(self, path: str) -> str:
        """Get environment synchronization status."""
        try:
            # Check if lock file is newer than environment
            lock_file = Path(path) / "pixi.lock"
            env_path = self._get_environment_path(path)

            if not lock_file.exists():
                return "no_lock_file"

            if not env_path or not Path(env_path).exists():
                return "environment_missing"

            # Simple check: if environment exists and lock file exists, assume synced
            # A more sophisticated check would compare timestamps
            return "synced"

        except Exception:
            return "unknown"

    def _get_python_version(self, path: str, config: dict) -> str | None:
        """Extract Python version from config or environment."""
        try:
            # Try to get from dependencies
            dependencies = config.get("dependencies", {})
            if "python" in dependencies:
                return dependencies["python"]

            # Try to get from environment
            env_path = self._get_environment_path(path)
            if env_path:
                python_path = Path(env_path) / "bin" / "python"
                if python_path.exists():
                    result = subprocess.run(
                        [str(python_path), "--version"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        return result.stdout.strip()
        except Exception:
            pass

        return None

    def _check_pixi_executable(self) -> bool:
        """Check if pixi executable is available."""
        try:
            result = subprocess.run(
                ["pixi", "--version"], capture_output=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def _check_environment_synced(self, path: str) -> bool:
        """Check if environment is synchronized with dependencies."""
        try:
            # Run pixi status or similar command to check sync status
            # For now, simplified check
            env_path = self._get_environment_path(path)
            lock_file = Path(path) / "pixi.lock"

            if not env_path or not lock_file.exists():
                return False

            # If both exist, assume synced (simplified)
            return Path(env_path).exists()

        except Exception:
            return False
