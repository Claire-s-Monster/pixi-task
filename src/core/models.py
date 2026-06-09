"""
Core domain models for pixi-task.

These models represent the pure business domain for pixi task execution
and environment management, replacing unrestricted bash pixi calls.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class PixiTaskResult(BaseModel):
    """Result of a pixi task execution"""

    task_name: str = Field(description="Name of executed pixi task")
    success: bool = Field(description="Whether task execution succeeded")
    stdout: str = Field(description="Standard output from task")
    stderr: str = Field(description="Standard error from task")
    exit_code: int = Field(description="Exit code from task execution")
    execution_time: float = Field(description="Execution time in seconds")
    working_dir: str = Field(description="Working directory where task was executed")
    environment: dict[str, str] = Field(
        default_factory=dict, description="Environment variables used"
    )
    command_line: str = Field(description="Full command line that was executed")
    started_at: str = Field(description="Task start timestamp (ISO8601)")
    completed_at: str = Field(description="Task completion timestamp (ISO8601)")

    @classmethod
    def create_success(
        cls,
        task_name: str,
        stdout: str,
        stderr: str,
        execution_time: float,
        working_dir: str,
        command_line: str,
        environment: dict[str, str] | None = None,
    ) -> "PixiTaskResult":
        """Create successful task result."""
        now = datetime.now(UTC).isoformat()
        return cls(
            task_name=task_name,
            success=True,
            stdout=stdout,
            stderr=stderr,
            exit_code=0,
            execution_time=execution_time,
            working_dir=working_dir,
            environment=environment or {},
            command_line=command_line,
            started_at=now,
            completed_at=now,
        )

    @classmethod
    def create_failure(
        cls,
        task_name: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        execution_time: float,
        working_dir: str,
        command_line: str,
        environment: dict[str, str] | None = None,
    ) -> "PixiTaskResult":
        """Create failed task result."""
        now = datetime.now(UTC).isoformat()
        return cls(
            task_name=task_name,
            success=False,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            execution_time=execution_time,
            working_dir=working_dir,
            environment=environment or {},
            command_line=command_line,
            started_at=now,
            completed_at=now,
        )


class PixiProjectInfo(BaseModel):
    """Information about a pixi project"""

    project_path: str = Field(description="Path to pixi project root")
    project_name: str = Field(description="Project name from pixi.toml")
    python_version: str | None = Field(None, description="Python version in use")
    environment_path: str | None = Field(None, description="Path to pixi environment")
    has_lock_file: bool = Field(description="Whether pixi.lock exists")
    dependencies: dict[str, str] = Field(
        default_factory=dict, description="Project dependencies"
    )
    dev_dependencies: dict[str, str] = Field(
        default_factory=dict, description="Development dependencies"
    )
    available_tasks: dict[str, str] = Field(
        default_factory=dict, description="Available pixi tasks"
    )
    channels: list[str] = Field(
        default_factory=list, description="Configured conda channels"
    )
    platforms: list[str] = Field(default_factory=list, description="Target platforms")
    environment_status: str = Field(description="Environment sync status")
    last_updated: str = Field(description="Last project update timestamp")

    @classmethod
    def create_empty(cls, project_path: str) -> "PixiProjectInfo":
        """Create empty project info for non-pixi directory."""
        return cls(
            project_path=project_path,
            project_name="",
            has_lock_file=False,
            environment_status="not_pixi_project",
            last_updated=datetime.now(UTC).isoformat(),
        )


class PixiTaskDefinition(BaseModel):
    """Definition of a pixi task"""

    name: str = Field(description="Task name")
    command: str = Field(description="Task command")
    description: str | None = Field(None, description="Task description")
    depends_on: list[str] = Field(default_factory=list, description="Task dependencies")
    environment: dict[str, str] = Field(
        default_factory=dict, description="Task environment variables"
    )
    working_dir: str | None = Field(None, description="Task working directory")
    timeout: int | None = Field(None, description="Task timeout in seconds")

    def is_executable(self) -> bool:
        """Check if task can be executed."""
        return bool(self.command and self.command.strip())


class PixiEnvironmentInfo(BaseModel):
    """Information about pixi environment"""

    environment_path: str = Field(description="Path to environment directory")
    python_executable: str | None = Field(None, description="Path to Python executable")
    python_version: str | None = Field(None, description="Python version")
    is_activated: bool = Field(description="Whether environment is currently activated")
    package_count: int = Field(description="Number of installed packages")
    environment_size_mb: float = Field(description="Environment size in MB")
    created_at: str | None = Field(None, description="Environment creation timestamp")
    last_modified: str | None = Field(None, description="Last modification timestamp")
    activation_vars: dict[str, str] = Field(
        default_factory=dict, description="Environment activation variables"
    )

    @classmethod
    def create_not_found(cls) -> "PixiEnvironmentInfo":
        """Create info for non-existent environment."""
        return cls(
            environment_path="",
            is_activated=False,
            package_count=0,
            environment_size_mb=0.0,
        )


class PixiDependency(BaseModel):
    """A pixi project dependency"""

    name: str = Field(description="Package name")
    version: str = Field(description="Version specification")
    channel: str | None = Field(None, description="Conda channel")
    build: str | None = Field(None, description="Build string")
    is_dev: bool = Field(default=False, description="Whether this is a dev dependency")
    is_pypi: bool = Field(
        default=False, description="Whether this is a PyPI dependency"
    )

    def to_spec_string(self) -> str:
        """Convert to pixi dependency specification string."""
        spec = f"{self.name}={self.version}" if self.version != "*" else self.name
        if self.channel:
            spec = f"{self.channel}::{spec}"
        return spec


class PixiExecutionContext(BaseModel):
    """Context for pixi command execution"""

    working_dir: str = Field(description="Working directory for execution")
    timeout: int = Field(default=300, description="Execution timeout in seconds")
    environment_vars: dict[str, str] = Field(
        default_factory=dict, description="Additional environment variables"
    )
    capture_output: bool = Field(
        default=True, description="Whether to capture stdout/stderr"
    )
    shell: bool = Field(default=False, description="Whether to execute in shell")
    pixi_executable: str = Field(
        default="/home/memento/.conda/envs/ClaudeCode/bin/pixi",
        description="Path to pixi executable",
    )
    environment: str | None = Field(
        default=None,
        description="Pixi environment to run the task in (e.g. 'default', 'test', 'docs')",
    )
    manifest_path: str | None = Field(
        default=None,
        description="Path to pixi.toml/pyproject.toml (for running tasks from a parent project's environment)",
    )

    def get_full_env(self) -> dict[str, str]:
        """Get full environment including additional vars."""
        import os

        env = os.environ.copy()
        env.update(self.environment_vars)
        return env


class PixiOperationResult(BaseModel):
    """Result of a pixi operation"""

    success: bool = Field(description="Whether operation succeeded")
    message: str = Field(description="Result message")
    data: dict[str, Any] | None = Field(None, description="Result data")
    error: str | None = Field(None, description="Error message if failed")
    execution_time: float = Field(description="Operation execution time")
    operation_type: str = Field(description="Type of operation performed")
    timestamp: str = Field(description="Operation timestamp")

    @classmethod
    def success_result(
        cls,
        message: str,
        operation_type: str,
        execution_time: float,
        data: dict[str, Any] | None = None,
    ) -> "PixiOperationResult":
        """Create successful operation result."""
        return cls(
            success=True,
            message=message,
            data=data,
            operation_type=operation_type,
            execution_time=execution_time,
            timestamp=datetime.now(UTC).isoformat(),
        )

    @classmethod
    def error_result(
        cls,
        message: str,
        operation_type: str,
        execution_time: float,
        error: str | None = None,
    ) -> "PixiOperationResult":
        """Create error operation result."""
        return cls(
            success=False,
            message=message,
            error=error or message,
            operation_type=operation_type,
            execution_time=execution_time,
            timestamp=datetime.now(UTC).isoformat(),
        )


class PixiHealthCheck(BaseModel):
    """Pixi project health check result"""

    is_pixi_project: bool = Field(description="Whether directory contains pixi.toml")
    pixi_executable_found: bool = Field(description="Whether pixi command is available")
    environment_exists: bool = Field(description="Whether pixi environment exists")
    environment_synced: bool = Field(description="Whether environment is up to date")
    lock_file_exists: bool = Field(description="Whether pixi.lock exists")
    issues: list[str] = Field(default_factory=list, description="Identified issues")
    recommendations: list[str] = Field(
        default_factory=list, description="Recommendations"
    )
    project_path: str = Field(description="Path that was checked")
    checked_at: str = Field(description="Health check timestamp")

    @classmethod
    def create_healthy(cls, project_path: str) -> "PixiHealthCheck":
        """Create healthy check result."""
        return cls(
            is_pixi_project=True,
            pixi_executable_found=True,
            environment_exists=True,
            environment_synced=True,
            lock_file_exists=True,
            project_path=project_path,
            checked_at=datetime.now(UTC).isoformat(),
        )

    @classmethod
    def create_unhealthy(
        cls,
        project_path: str,
        issues: list[str],
        recommendations: list[str] | None = None,
    ) -> "PixiHealthCheck":
        """Create unhealthy check result."""
        return cls(
            is_pixi_project=False,
            pixi_executable_found=False,
            environment_exists=False,
            environment_synced=False,
            lock_file_exists=False,
            issues=issues,
            recommendations=recommendations or [],
            project_path=project_path,
            checked_at=datetime.now(UTC).isoformat(),
        )

    def is_healthy(self) -> bool:
        """Check if project is healthy."""
        return (
            self.is_pixi_project
            and self.pixi_executable_found
            and self.environment_exists
            and len(self.issues) == 0
        )


class SystemHealth(BaseModel):
    """System health information for monitoring pixi shell MCP server"""

    healthy: bool = Field(description="Overall system health status")
    available_functions: int = Field(description="Number of available pixi operations")
    recent_executions: int = Field(description="Recent task executions count")
    error_rate: float = Field(description="Error rate percentage")
    average_response_time: float = Field(description="Average response time in seconds")
    security_alerts: list[str] = Field(
        default_factory=list, description="Security alerts"
    )
    resource_usage: dict[str, Any] = Field(
        default_factory=dict, description="System resource usage"
    )
    last_health_check: str = Field(description="Last health check timestamp")
