#!/usr/bin/env python3
"""
ClaudeCode Shell MCP Server - Secure Function Execution

A Model Context Protocol server that provides controlled access to the 195+ claudecode_* functions,
replacing unrestricted Bash tool usage with validated, safe function execution.

Key Features:
- Secure function execution with comprehensive validation
- Function whitelist (only claudecode_* functions allowed)
- Parameter sanitization and security checks
- Timeout protection and resource limits
- Comprehensive audit logging
- Function discovery and validation
- Drop-in replacement for Bash("claudecode_...") usage

Security Model:
- ONLY allows functions starting with 'claudecode_'
- Validates all arguments for dangerous patterns
- Escapes shell metacharacters
- Enforces timeout limits (1-300 seconds)
- Logs all executions for security audit
"""

import logging
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# Ensure the src directory is in the path for imports
src_dir = Path(__file__).parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from core.container import Container

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("claudecode_shell.server")

# Initialize dependency injection container
container = Container()

# Initialize FastMCP application
app: FastMCP = FastMCP("claudecode-shell", version="0.1.0")


# =============================================================================
# CORE FUNCTION EXECUTION
# =============================================================================


@app.tool()
def execute_claudecode_function(
    function_name: str,
    args: list[str] = [],
    working_dir: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """
    Execute a claudecode_* function with validation and security checks.

    Use this as a DROP-IN REPLACEMENT for Bash("claudecode_...") calls:

    Migration Pattern:
    - OLD: Bash("claudecode_system_info load")
    - NEW: execute_claudecode_function("claudecode_system_info", ["load"])

    Common Usage Examples:
    - execute_claudecode_function("claudecode_system_info", ["load"])
    - execute_claudecode_function("claudecode_git_status")
    - execute_claudecode_function("claudecode_quality_check", ["--fast"])
    - execute_claudecode_function("claudecode_pixi_compliance")
    - execute_claudecode_function("claudecode_test_analysis")

    Security Features:
    - ONLY allows functions starting with 'claudecode_'
    - Validates and sanitizes all arguments
    - Prevents shell injection attacks
    - Enforces timeout limits (1-300 seconds)
    - Logs all executions for audit

    Performance:
    - Sub-100ms execution overhead vs direct Bash
    - Same stdout/stderr/exit_code behavior as Bash
    - Identical error handling and semantics

    Returns: {"success": bool, "stdout": str, "stderr": str, "exit_code": int, "execution_time": float}

    This function maintains FULL BACKWARD COMPATIBILITY with existing claudecode functions
    while providing comprehensive security validation and audit logging.
    """
    try:
        return container.shell_service.execute_function(
            function_name, args, working_dir, timeout_seconds
        )
    except Exception as e:
        logger.error(f"Error in execute_claudecode_function: {e}")
        return {
            "success": False,
            "stdout": "",
            "stderr": f"MCP server error: {str(e)}",
            "exit_code": 1,
            "execution_time": 0.0,
        }


@app.tool()
def list_available_functions(category: str | None = None) -> dict[str, Any]:
    """
    List available claudecode functions with descriptions.

    Use for function discovery and agent development:
    - list_available_functions() for all functions
    - list_available_functions("git") for git-related functions only
    - list_available_functions("python") for Python quality functions

    Categories include:
    - "atomic": Atomic design and refactoring functions
    - "git": Git workflow and repository functions
    - "python": Python quality, linting, and analysis functions
    - "quality": Quality assurance and testing functions
    - "session": Session management and continuity functions
    - "agent": Agent lifecycle and management functions
    - "system": System information and resource functions
    - "pixi": PIXI package management functions
    - "ci": CI/CD workflow and monitoring functions
    - "security": Security scanning and validation functions

    Returns: {"functions": [...], "total_count": int, "categories": {...}}

    Perfect for agent developers who need to discover available claudecode functions
    or validate that required functions exist before attempting execution.
    """
    try:
        return container.shell_service.list_available_functions(category)
    except Exception as e:
        logger.error(f"Error in list_available_functions: {e}")
        return {
            "functions": [],
            "total_count": 0,
            "categories": {},
            "error": f"Function discovery failed: {str(e)}",
        }


@app.tool()
def validate_function_exists(function_name: str) -> dict[str, Any]:
    """
    Check if a claudecode function exists and is accessible.

    Use before executing functions to ensure they're available:
    - validate_function_exists("claudecode_system_info")
    - validate_function_exists("claudecode_git_status")

    Essential for error handling in agents:
    ```python
    validation = validate_function_exists("claudecode_custom_function")
    if validation["exists"]:
        result = execute_claudecode_function("claudecode_custom_function")
    else:
        # Handle missing function gracefully
        pass
    ```

    Returns: {"exists": bool, "executable": bool, "description": str, "path": str}

    Helps agents provide better error messages when required claudecode functions
    are missing or not properly installed.
    """
    try:
        return container.shell_service.validate_function_exists(function_name)
    except Exception as e:
        logger.error(f"Error in validate_function_exists: {e}")
        return {
            "exists": False,
            "executable": False,
            "description": f"Validation error: {str(e)}",
            "path": None,
            "error": str(e),
        }


# =============================================================================
# ADVANCED EXECUTION FEATURES
# =============================================================================


@app.tool()
def execute_bulk_functions(operations: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Execute multiple claudecode functions atomically.

    Use for batch operations that must succeed or fail together:

    Example operations:
    [
        {"function_name": "claudecode_git_status"},
        {"function_name": "claudecode_quality_check", "args": ["--fast"]},
        {"function_name": "claudecode_test_analysis", "timeout_seconds": 60}
    ]

    Atomic semantics: Either ALL operations succeed, or ALL are rolled back.
    Perfect for complex workflows that require consistency.

    Returns: {"success": bool, "results": [...], "errors": [...], "completed_operations": int}

    Most individual agents should use execute_claudecode_function() instead.
    This is primarily for orchestration agents managing complex workflows.
    """
    try:
        return container.shell_service.execute_bulk_functions(operations)
    except Exception as e:
        logger.error(f"Error in execute_bulk_functions: {e}")
        return {
            "success": False,
            "results": [],
            "errors": [f"Bulk execution failed: {str(e)}"],
            "partial_success": False,
            "completed_operations": 0,
            "total_operations": len(operations) if operations else 0,
        }


# =============================================================================
# MONITORING AND DEBUGGING
# =============================================================================


@app.tool()
def get_execution_stats(hours: int = 24) -> dict[str, Any]:
    """
    Get execution statistics for monitoring and debugging.

    Use for performance monitoring and optimization:
    - get_execution_stats(1) for last hour
    - get_execution_stats(24) for last day (default)
    - get_execution_stats(168) for last week

    Returns comprehensive metrics including:
    - Total executions and success rates
    - Most frequently used functions
    - Average execution times
    - Security events and violations

    Returns: {"total_executions": int, "success_rate": float, "most_used_functions": {...}}

    Essential for identifying performance bottlenecks and optimizing agent workflows.
    Generally only needed for debugging or maintenance workflows.
    """
    try:
        return container.shell_service.get_execution_stats(hours)
    except Exception as e:
        logger.error(f"Error in get_execution_stats: {e}")
        return {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "success_rate": 0.0,
            "average_execution_time": 0.0,
            "most_used_functions": {},
            "error": str(e),
        }


@app.tool()
def get_system_health() -> dict[str, Any]:
    """
    Get system health information for monitoring.

    Use for health checks and system monitoring:
    - Monitor claudecode function availability
    - Check system resource usage
    - Identify security alerts or issues

    Returns health status including:
    - Available function count
    - Recent execution metrics
    - Error rates and response times
    - Security alerts and resource usage

    Returns: {"healthy": bool, "available_functions": int, "security_alerts": [...]}

    Critical for system monitoring and identifying infrastructure issues
    that might affect claudecode function execution.
    """
    try:
        return container.shell_service.get_system_health()
    except Exception as e:
        logger.error(f"Error in get_system_health: {e}")
        return {
            "healthy": False,
            "available_functions": 0,
            "recent_executions": 0,
            "error_rate": 100.0,
            "average_response_time": 0.0,
            "security_alerts": [f"Health check failed: {str(e)}"],
            "resource_usage": {},
            "error": str(e),
        }


@app.tool()
def cleanup_cache(max_age_minutes: int = 60) -> dict[str, Any]:
    """
    Clean up cached function discovery and validation data.

    Use for maintenance and memory management:
    - cleanup_cache(30) for aggressive cleanup
    - cleanup_cache(60) for normal maintenance (default)
    - cleanup_cache(180) for conservative cleanup

    Clears cached function validation and discovery results to free memory
    and ensure fresh data on subsequent requests.

    Returns: {"success": bool, "cleaned_entries": int}

    Usually not needed for individual agents - the cache automatically manages TTL.
    Primarily for maintenance workflows or when function availability changes.
    """
    try:
        return container.shell_service.cleanup_cache(max_age_minutes)
    except Exception as e:
        logger.error(f"Error in cleanup_cache: {e}")
        return {"success": False, "cleaned_entries": 0, "error": str(e)}


# =============================================================================
# INFORMATION RESOURCES
# =============================================================================


@app.resource("claudecode-shell://functions")
def get_all_functions() -> dict[str, Any]:
    """Get complete list of available claudecode functions."""
    try:
        return container.shell_service.list_available_functions()
    except Exception as e:
        logger.error(f"Error getting all functions: {e}")
        return {"error": f"Failed to get functions: {str(e)}"}


@app.resource("claudecode-shell://functions/{category}")
def get_functions_by_category(category: str) -> dict[str, Any]:
    """Get claudecode functions filtered by category."""
    try:
        return container.shell_service.list_available_functions(category)
    except Exception as e:
        logger.error(f"Error getting functions for category {category}: {e}")
        return {"error": f"Failed to get functions for category {category}: {str(e)}"}


@app.resource("claudecode-shell://health")
def get_server_health() -> dict[str, Any]:
    """Get claudecode shell server health information."""
    try:
        health = container.shell_service.get_system_health()

        # Add server-specific health info
        health["server_status"] = "running"
        health["mcp_version"] = "0.1.0"
        health["security_model"] = "claudecode_whitelist"

        return health
    except Exception as e:
        logger.error(f"Error getting server health: {e}")
        return {
            "healthy": False,
            "server_status": "error",
            "error": f"Health check failed: {str(e)}",
        }


@app.resource("claudecode-shell://stats")
def get_server_stats() -> dict[str, Any]:
    """Get server execution statistics."""
    try:
        return container.shell_service.get_execution_stats(24)
    except Exception as e:
        logger.error(f"Error getting server stats: {e}")
        return {"error": f"Failed to get server stats: {str(e)}"}


# =============================================================================
# APPLICATION ENTRY POINT
# =============================================================================


def main():
    """Main entry point for the MCP server."""
    import sys

    # Check if we're running in test mode
    if "pytest" in sys.modules or "test" in sys.argv:
        logger.info("Running in test mode")

    logger.info("ClaudeCode Shell MCP Server starting...")
    logger.info("Working directory: %s", container.get_working_directory())

    # Validate system setup
    try:
        health = container.shell_service.get_system_health()
        logger.info(
            "System health check: %s functions available", health["available_functions"]
        )

        if not health["healthy"]:
            logger.warning(
                "System health issues detected: %s", health.get("security_alerts", [])
            )
    except Exception as e:
        logger.error("Failed to perform initial health check: %s", e)
        # Continue anyway - some functions might still work

    logger.info("ClaudeCode Shell MCP Server ready for secure function execution")
    logger.info(
        "Security model: claudecode_* function whitelist with argument validation"
    )

    app.run()


if __name__ == "__main__":
    main()
