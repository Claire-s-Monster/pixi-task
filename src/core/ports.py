"""
Port interfaces for Pixi Shell MCP Server.

This module defines the abstract interfaces for external dependencies,
following hexagonal architecture patterns for secure pixi task execution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.models import (
    PixiExecutionContext,
    PixiHealthCheck,
    PixiOperationResult,
    PixiProjectInfo,
    PixiTaskResult,
    PixiEnvironmentInfo,
)


class PixiExecutorPort(ABC):
    """Port for executing pixi tasks and commands securely."""

    @abstractmethod
    def run_task(
        self, task_name: str, args: list[str], context: PixiExecutionContext
    ) -> PixiTaskResult:
        """Execute a pixi task with arguments."""
        pass

    @abstractmethod
    def execute_command(
        self, command: list[str], context: PixiExecutionContext
    ) -> PixiTaskResult:
        """Execute arbitrary command in pixi environment."""
        pass

    @abstractmethod
    def install(self, context: PixiExecutionContext) -> PixiTaskResult:
        """Install/sync pixi environment and dependencies."""
        pass

    @abstractmethod
    def check_pixi_available(self) -> bool:
        """Check if pixi executable is available."""
        pass


class PixiProjectPort(ABC):
    """Port for pixi project management and information."""

    @abstractmethod
    def is_pixi_project(self, path: str) -> bool:
        """Check if directory contains a pixi project."""
        pass

    @abstractmethod
    def get_project_info(self, path: str) -> PixiProjectInfo:
        """Get comprehensive pixi project information."""
        pass

    @abstractmethod
    def get_available_tasks(self, path: str) -> dict[str, str]:
        """Get available pixi tasks with descriptions."""
        pass

    @abstractmethod
    def add_dependency(
        self,
        package: str,
        channel: str | None = None,
        is_dev: bool = False,
        working_dir: str | None = None,
    ) -> PixiOperationResult:
        """Add a dependency to pixi project."""
        pass

    @abstractmethod
    def remove_dependency(
        self, package: str, is_dev: bool = False, working_dir: str | None = None
    ) -> PixiOperationResult:
        """Remove a dependency from pixi project."""
        pass

    @abstractmethod
    def check_health(self, path: str) -> PixiHealthCheck:
        """Perform comprehensive health check of pixi project."""
        pass

    @abstractmethod
    def init_project(
        self, path: str, template: str | None = None
    ) -> PixiOperationResult:
        """Initialize a new pixi project."""
        pass

    @abstractmethod
    def get_environment_info(self, path: str) -> PixiEnvironmentInfo:
        """Get pixi environment information."""
        pass


class LoggingPort(ABC):
    """Port for structured logging."""

    @abstractmethod
    def log_info(self, message: str, context: dict[str, Any] | None = None) -> None:
        """Log an informational message."""
        pass

    @abstractmethod
    def log_warning(self, message: str, context: dict[str, Any] | None = None) -> None:
        """Log a warning message."""
        pass

    @abstractmethod
    def log_error(self, message: str, context: dict[str, Any] | None = None) -> None:
        """Log an error message."""
        pass

    @abstractmethod
    def log_task_execution(
        self, task_name: str, context: dict[str, Any] | None = None
    ) -> None:
        """Log a pixi task execution event."""
        pass


class ValidationPort(ABC):
    """Port for input validation and sanitization."""

    @abstractmethod
    def validate_task_name(self, task_name: str) -> bool:
        """Validate a pixi task name for security."""
        pass

    @abstractmethod
    def validate_arguments(self, args: list[str]) -> list[str]:
        """Validate and sanitize pixi task arguments."""
        pass

    @abstractmethod
    def validate_working_directory(self, path: str) -> bool:
        """Validate a working directory path for security."""
        pass

    @abstractmethod
    def sanitize_environment_vars(self, env_vars: dict[str, str]) -> dict[str, str]:
        """Sanitize environment variables for safe execution."""
        pass

    @abstractmethod
    def validate_package_name(self, package: str) -> bool:
        """Validate a package name for dependencies."""
        pass


class EnvironmentPort(ABC):
    """Port for environment and system interactions."""

    @abstractmethod
    def get_working_directory(self) -> str:
        """Get the current working directory."""
        pass

    @abstractmethod
    def get_pixi_executable_path(self) -> str | None:
        """Get the path to pixi executable."""
        pass

    @abstractmethod
    def check_pixi_installed(self) -> bool:
        """Check if pixi is installed and available."""
        pass

    @abstractmethod
    def get_environment_variables(self) -> dict[str, str]:
        """Get current environment variables."""
        pass

    @abstractmethod
    def resolve_project_path(self, path: str | None = None) -> str:
        """Resolve project path, defaulting to current directory."""
        pass


class TimeoutPort(ABC):
    """Port for timeout and resource management."""

    @abstractmethod
    def execute_with_timeout(
        self,
        command: list[str],
        timeout_seconds: int,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, int, float]:
        """Execute a command with timeout and return (stdout, stderr, exit_code, execution_time)."""
        pass

    @abstractmethod
    def check_resource_limits(self) -> dict[str, Any]:
        """Check current resource usage and limits."""
        pass


class PixiConfigPort(ABC):
    """Port for reading and parsing pixi configuration files."""

    @abstractmethod
    def read_pixi_toml(self, project_path: str) -> dict[str, Any]:
        """Read and parse pixi.toml file."""
        pass

    @abstractmethod
    def check_lock_file_exists(self, project_path: str) -> bool:
        """Check if pixi.lock file exists."""
        pass

    @abstractmethod
    def get_project_metadata(self, project_path: str) -> dict[str, Any]:
        """Get project metadata from pixi.toml."""
        pass

    @abstractmethod
    def parse_tasks(self, project_path: str) -> dict[str, str]:
        """Parse tasks from pixi.toml."""
        pass

    @abstractmethod
    def parse_dependencies(
        self, project_path: str
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Parse dependencies and dev-dependencies from pixi.toml."""
        pass
