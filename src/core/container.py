"""
Dependency injection container for Pixi Shell MCP Server.

This module provides centralized dependency management using the same patterns
as the agent-cache server, ensuring consistent architecture.
"""

import os

from adapters.environment import EnvironmentAdapter
from adapters.execution import PixiExecutionAdapter
from adapters.logging import LoggingAdapter
from adapters.project import PixiProjectAdapter
from adapters.validation import ValidationAdapter
from core.pixi_service import PixiShellService


class Container:
    """
    Dependency injection container for the Pixi Shell server.

    Manages all dependencies and provides a clean interface for
    service instantiation with proper configuration.
    """

    def __init__(self, working_dir: str | None = None):
        """Initialize container with optional working directory override."""
        self._working_dir = working_dir or os.getcwd()
        self._services = {}
        self._adapters = {}
        self._initialize_adapters()
        self._initialize_services()

    def _initialize_adapters(self) -> None:
        """Initialize all adapter instances."""
        # Environment adapter
        self._adapters["environment"] = EnvironmentAdapter(
            working_dir=self._working_dir
        )

        # Logging adapter
        self._adapters["logging"] = LoggingAdapter()

        # Validation adapter
        self._adapters["validation"] = ValidationAdapter()

        # Pixi project adapter
        self._adapters["project"] = PixiProjectAdapter(
            environment=self._adapters["environment"], logging=self._adapters["logging"]
        )

        # Pixi execution adapter
        self._adapters["execution"] = PixiExecutionAdapter(
            environment=self._adapters["environment"],
            logging=self._adapters["logging"],
            validation=self._adapters["validation"],
        )

    def _initialize_services(self) -> None:
        """Initialize all service instances."""
        # Core pixi service
        self._services["pixi"] = PixiShellService(
            pixi_executor=self._adapters["execution"],
            pixi_project=self._adapters["project"],
            logging=self._adapters["logging"],
            validation=self._adapters["validation"],
        )

    @property
    def pixi_service(self) -> PixiShellService:
        """Get the main pixi service."""
        return self._services["pixi"]

    @property
    def environment(self) -> EnvironmentAdapter:
        """Get the environment adapter."""
        return self._adapters["environment"]

    @property
    def logging(self) -> LoggingAdapter:
        """Get the logging adapter."""
        return self._adapters["logging"]

    def get_working_directory(self) -> str:
        """Get the configured working directory."""
        return self._working_dir

    def cleanup(self) -> None:
        """Clean up resources when shutting down."""
        try:
            # Clean up any resources that need explicit cleanup
            for adapter in self._adapters.values():
                if hasattr(adapter, "cleanup"):
                    adapter.cleanup()

            self._adapters["logging"].log_info("Container cleanup completed")
        except Exception as e:
            print(f"Error during container cleanup: {e}")  # Fallback logging
