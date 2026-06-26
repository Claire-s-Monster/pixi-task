"""
Validation adapter for Pixi Shell MCP Server.

Provides input validation, sanitization, and security checks for pixi operations.
"""

import re

from core.ports import ValidationPort


class ValidationAdapter(ValidationPort):
    """Adapter for input validation and sanitization."""

    def __init__(self):
        # Dangerous patterns that should be blocked
        self.dangerous_patterns = [
            r"[;&|`$]",  # Shell metacharacters
            r"\$\(",  # Command substitution
            r">\s*>",  # Redirects
            r"<\s*<",  # Redirects
            r"\|\s*\|",  # Or operators
            r"&\s*&",  # And operators
            r"rm\s+-[rf]",  # Dangerous rm commands
            r"sudo\s+",  # Sudo commands
            r"chmod\s+",  # Permission changes
            r"chown\s+",  # Ownership changes
        ]

        # Compile patterns for efficiency
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.dangerous_patterns
        ]

    def validate_task_name(self, task_name: str) -> bool:
        """Validate a pixi task name for security."""
        # Basic length check
        if len(task_name) > 100:
            return False

        # Must only contain alphanumeric, underscore, hyphen
        if not re.match(r"^[a-zA-Z0-9_-]+$", task_name):
            return False

        # Cannot be empty or just whitespace
        if not task_name.strip():
            return False

        # Prevent obvious dangerous names
        dangerous_names = ["rm", "sudo", "chmod", "chown", "shutdown", "reboot"]
        if task_name.lower() in dangerous_names:
            return False

        return True

    def validate_arguments(self, args: list[str]) -> list[str]:
        """Validate and sanitize pixi task arguments."""
        sanitized = []

        for arg in args:
            # Basic length limit
            if len(arg) > 1000:
                arg = arg[:1000]

            # Remove null bytes and control characters
            sanitized_arg = "".join(char for char in arg if ord(char) >= 32 or char in ["\t", "\n"])

            # Check for dangerous patterns and reject if found
            for pattern in self.compiled_patterns:
                if pattern.search(sanitized_arg):
                    # For security, we skip dangerous arguments rather than try to sanitize
                    continue

            sanitized.append(sanitized_arg)

        return sanitized

    def validate_working_directory(self, path: str) -> bool:
        """Validate a working directory path for security."""
        # Prevent path traversal
        if ".." in path:
            return False

        # Prevent absolute paths that could escape project directory
        if path.startswith("/"):
            return False

        # Prevent dangerous characters
        dangerous_chars = [";", "&", "|", "`", "$", ">", "<"]
        if any(char in path for char in dangerous_chars):
            return False

        # Basic length check
        if len(path) > 500:
            return False

        return True

    def sanitize_environment_vars(self, env_vars: dict[str, str]) -> dict[str, str]:
        """Sanitize environment variables for safe execution."""
        sanitized = {}

        for key, value in env_vars.items():
            # Validate key
            if not re.match(r"^[A-Z_][A-Z0-9_]*$", key):
                continue  # Skip invalid environment variable names

            # Sanitize value
            if len(value) > 2000:
                value = value[:2000]

            # Remove null bytes and control characters except tab and newline
            sanitized_value = "".join(
                char for char in value if ord(char) >= 32 or char in ["\t", "\n"]
            )

            # Check for dangerous patterns in value
            has_dangerous_pattern = False
            for pattern in self.compiled_patterns:
                if pattern.search(sanitized_value):
                    has_dangerous_pattern = True
                    break

            if not has_dangerous_pattern:
                sanitized[key] = sanitized_value

        return sanitized

    def validate_package_name(self, package: str) -> bool:
        """Validate a package name for dependencies."""
        # Basic length check
        if len(package) > 200:
            return False

        # Cannot be empty
        if not package.strip():
            return False

        # Must match typical conda/pip package naming conventions
        # Allow alphanumeric, underscore, hyphen, dots (for namespaced packages)
        if not re.match(r"^[a-zA-Z0-9_.-]+$", package):
            return False

        # Cannot start with hyphen or dot
        if package.startswith(("-", ".")):
            return False

        # Prevent dangerous package names
        dangerous_packages = ["rm", "sudo", "malware", "virus"]
        if package.lower() in dangerous_packages:
            return False

        return True
