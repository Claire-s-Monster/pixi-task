"""
Logging adapter for Pixi Shell MCP Server.

Provides structured logging with pixi task execution tracking.
"""

import json
import logging
import sys
from typing import Any

from core.ports import LoggingPort


class LoggingAdapter(LoggingPort):
    """Adapter for structured logging with security event support."""

    def __init__(self):
        # Configure main logger
        self.logger = logging.getLogger("pixi_task")
        self.logger.setLevel(logging.INFO)

        # Configure security logger
        self.security_logger = logging.getLogger("pixi_task.security")
        self.security_logger.setLevel(logging.INFO)

        # Set up console handler if not already configured
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.INFO)

            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)

            self.logger.addHandler(handler)
            self.security_logger.addHandler(handler)

    def log_info(self, message: str, context: dict[str, Any] | None = None) -> None:
        """Log an informational message."""
        if context:
            enhanced_message = (
                f"{message} | Context: {json.dumps(context, default=str)}"
            )
        else:
            enhanced_message = message

        self.logger.info(enhanced_message)

    def log_warning(self, message: str, context: dict[str, Any] | None = None) -> None:
        """Log a warning message."""
        if context:
            enhanced_message = (
                f"{message} | Context: {json.dumps(context, default=str)}"
            )
        else:
            enhanced_message = message

        self.logger.warning(enhanced_message)

    def log_error(self, message: str, context: dict[str, Any] | None = None) -> None:
        """Log an error message."""
        if context:
            enhanced_message = (
                f"{message} | Context: {json.dumps(context, default=str)}"
            )
        else:
            enhanced_message = message

        self.logger.error(enhanced_message)

    def log_task_execution(
        self, task_name: str, context: dict[str, Any] | None = None
    ) -> None:
        """Log a pixi task execution event."""
        if context:
            enhanced_message = f"TASK EXECUTED: {task_name} | Context: {json.dumps(context, default=str)}"
        else:
            enhanced_message = f"TASK EXECUTED: {task_name}"

        self.logger.info(enhanced_message)

    def log_security_event(
        self, event: str, context: dict[str, Any] | None = None
    ) -> None:
        """Log a security-related event."""
        if context:
            enhanced_event = (
                f"SECURITY: {event} | Context: {json.dumps(context, default=str)}"
            )
        else:
            enhanced_event = f"SECURITY: {event}"

        self.security_logger.warning(enhanced_event)
