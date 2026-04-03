"""
Environment adapter for Pixi Shell MCP Server.

Handles system environment interactions, path validation, and pixi project detection.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from core.models import SystemHealth
from core.ports import EnvironmentPort


class EnvironmentAdapter(EnvironmentPort):
    """Adapter for environment and system interactions."""

    def __init__(self, working_dir: str):
        self.working_dir = working_dir

    def get_working_directory(self) -> str:
        """Get the current working directory."""
        return self.working_dir

    def validate_working_directory(self, path: str) -> bool:
        """Validate a working directory path for security."""
        try:
            # Basic security checks
            if not path:
                return False

            # Prevent path traversal
            if ".." in path or path.startswith("/"):
                return False

            # Must be relative to current working directory
            full_path = os.path.join(self.working_dir, path)
            normalized_path = os.path.normpath(full_path)

            # Ensure path doesn't escape working directory
            if not normalized_path.startswith(self.working_dir):
                return False

            return True

        except Exception:
            return False

    def check_pixi_available(self) -> bool:
        """Check if pixi executable is available."""
        try:
            result = subprocess.run(
                ["pixi", "--version"], capture_output=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_pixi_path(self) -> str | None:
        """Get path to pixi executable."""
        return shutil.which("pixi")

    def get_pixi_executable_path(self) -> str | None:
        """Get the path to pixi executable."""
        return self.get_pixi_path()

    def check_pixi_installed(self) -> bool:
        """Check if pixi is installed and available."""
        return self.check_pixi_available()

    def get_environment_variables(self) -> dict[str, str]:
        """Get current environment variables."""
        return dict(os.environ)

    def resolve_project_path(self, path: str | None = None) -> str:
        """Resolve project path, defaulting to current directory."""
        if path is None:
            return self.working_dir

        if os.path.isabs(path):
            return path

        return os.path.join(self.working_dir, path)

    def get_system_health(self) -> SystemHealth:
        """Get system health information."""
        try:
            # Check pixi availability
            pixi_available = self.check_pixi_available()
            available_functions = (
                14 if pixi_available else 0
            )  # Count of pixi MCP functions

            # Basic resource checks
            resource_usage = self._get_resource_usage()

            # Determine health status
            healthy = (
                pixi_available
                and resource_usage.get("disk_usage_percent", 0) < 90
                and resource_usage.get("load_average", 0) < 10.0
            )

            security_alerts = []
            if not pixi_available:
                security_alerts.append(
                    "Pixi executable not found - install pixi for functionality"
                )

            return SystemHealth(
                healthy=healthy,
                available_functions=available_functions,
                recent_executions=0,  # Would be tracked by metrics
                error_rate=0.0,  # Would be calculated from execution history
                average_response_time=0.05,  # Estimated
                security_alerts=security_alerts,
                resource_usage=resource_usage,
                last_health_check=f"{time.time():.6f}",
            )

        except Exception as e:
            return SystemHealth(
                healthy=False,
                available_functions=0,
                recent_executions=0,
                error_rate=100.0,
                average_response_time=0.0,
                security_alerts=[f"Health check failed: {str(e)}"],
                resource_usage={},
                last_health_check=f"{time.time():.6f}",
            )

    def _get_resource_usage(self) -> dict[str, Any]:
        """Get basic system resource usage."""
        resource_usage = {}

        try:
            # Load average
            if os.path.exists("/proc/loadavg"):
                with open("/proc/loadavg") as f:
                    load_avg = float(f.read().split()[0])
                    resource_usage["load_average"] = load_avg
        except Exception:
            resource_usage["load_average"] = 0.0

        try:
            # Disk usage
            statvfs = os.statvfs(self.working_dir)
            total_space = statvfs.f_frsize * statvfs.f_blocks
            free_space = statvfs.f_frsize * statvfs.f_available
            used_space = total_space - free_space
            disk_usage_percent = (
                (used_space / total_space * 100) if total_space > 0 else 0
            )
            resource_usage["disk_usage_percent"] = disk_usage_percent
        except Exception:
            resource_usage["disk_usage_percent"] = 0.0

        try:
            # Memory usage
            if os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo") as f:
                    meminfo = f.read()
                    for line in meminfo.split("\n"):
                        if line.startswith("MemAvailable:"):
                            available_kb = int(line.split()[1])
                            resource_usage["memory_available_mb"] = available_kb // 1024
                            break
        except Exception:
            resource_usage["memory_available_mb"] = 0

        return resource_usage
