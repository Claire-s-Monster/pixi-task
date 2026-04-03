#!/usr/bin/env python3
"""
Pixi Shell MCP Server - Secure Pixi Task Execution

A Model Context Protocol server that provides controlled access to pixi tasks and commands,
eliminating agent bash circumvention and providing safe pixi project management.

Key Features:
- Secure pixi task execution with comprehensive validation
- Project-aware task discovery and execution
- Environment management and dependency handling
- Timeout protection and resource limits
- Comprehensive audit logging
- Drop-in replacement for Bash("pixi ...") usage

Security Model:
- Validates all task names and arguments
- Escapes shell metacharacters and dangerous patterns
- Enforces timeout limits for all operations
- Requires pixi.toml presence for project operations
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
logger = logging.getLogger("pixi_shell.server")

# Initialize dependency injection container
container = Container()

# Initialize FastMCP application
app: FastMCP = FastMCP("pixi-shell", version="0.1.0")


# =============================================================================
# TIER 1: CORE TASK EXECUTION FUNCTIONS (HIGHEST PRIORITY)
# =============================================================================


@app.tool()
def pixi_run_task(
    task_name: str,
    args: list[str] = [],
    working_dir: str | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """
    Execute a pixi task with arguments.
    Essential for: pixi run test, pixi run lint, pixi run build, pixi run dev

    Common usage that agents try to bypass:
    - Instead of: Bash("pixi run test")
    - Use: pixi_run_task("test")
    - Instead of: Bash("pixi run lint --fix")
    - Use: pixi_run_task("lint", ["--fix"])

    Returns: {"success": bool, "stdout": str, "stderr": str, "exit_code": int, "execution_time": float}

    This function eliminates bash circumvention by providing direct, secure pixi task execution
    with proper working directory detection and environment activation.
    """
    try:
        return container.pixi_service.run_task(task_name, args, working_dir, timeout)
    except Exception as e:
        logger.error(f"Error in pixi_run_task: {e}")
        return {
            "success": False,
            "stdout": "",
            "stderr": f"MCP server error: {str(e)}",
            "exit_code": 1,
            "execution_time": 0.0,
            "task_name": task_name,
            "working_dir": working_dir or "current",
        }


@app.tool()
def pixi_list_tasks(working_dir: str | None = None) -> dict[str, Any]:
    """
    List all available pixi tasks with descriptions.
    Returns: {"tasks": {"test": "Run pytest", "lint": "Run ruff", ...}}

    Critical for: Agent discovery of available tasks

    Enables agents to programmatically discover what tasks are available in a pixi project,
    preventing failed task execution attempts and enabling intelligent workflow decisions.
    """
    try:
        return container.pixi_service.list_tasks(working_dir)
    except Exception as e:
        logger.error(f"Error in pixi_list_tasks: {e}")
        return {"tasks": {}, "error": f"Task discovery failed: {str(e)}"}


@app.tool()
def pixi_task_exists(task_name: str, working_dir: str | None = None) -> dict[str, Any]:
    """
    Check if a pixi task exists before attempting to run it.
    Returns: {"exists": bool, "working_dir": str}

    Prevents: Failed task execution attempts

    Essential for agent validation before task execution, enabling graceful handling
    of missing tasks and better error messages.
    """
    try:
        exists = container.pixi_service.task_exists(task_name, working_dir)
        return {
            "exists": exists,
            "task_name": task_name,
            "working_dir": working_dir or "current",
        }
    except Exception as e:
        logger.error(f"Error in pixi_task_exists: {e}")
        return {
            "exists": False,
            "task_name": task_name,
            "working_dir": working_dir or "current",
            "error": str(e),
        }


@app.tool()
def pixi_install(working_dir: str | None = None) -> dict[str, Any]:
    """
    Install/sync pixi environment and dependencies.
    Essential for: Environment setup, dependency resolution

    Replaces: Bash("pixi install")

    Provides safe, timeout-controlled environment installation with proper error handling
    and progress reporting. Critical for project setup and dependency synchronization.
    """
    try:
        return container.pixi_service.install(working_dir)
    except Exception as e:
        logger.error(f"Error in pixi_install: {e}")
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Install error: {str(e)}",
            "execution_time": 0.0,
        }


# =============================================================================
# TIER 2: ENVIRONMENT AND PROJECT MANAGEMENT
# =============================================================================


@app.tool()
def pixi_info(working_dir: str | None = None) -> dict[str, Any]:
    """
    Get pixi project information and environment status.
    Returns: Environment path, Python version, dependencies, etc.

    Critical for: Environment validation, troubleshooting

    Provides comprehensive project status including environment state, dependency information,
    and configuration details essential for debugging and project management.
    """
    try:
        return container.pixi_service.get_info(working_dir)
    except Exception as e:
        logger.error(f"Error in pixi_info: {e}")
        return {"is_pixi_project": False, "error": f"Project info failed: {str(e)}"}


@app.tool()
def pixi_project_status(working_dir: str | None = None) -> dict[str, Any]:
    """
    Get comprehensive project status.
    Returns: Lock file status, environment status, task availability

    Essential for: Health checks and project validation

    Provides complete project health assessment including environment sync status,
    dependency state, and configuration validation for troubleshooting and monitoring.
    """
    try:
        return container.pixi_service.get_project_status(working_dir)
    except Exception as e:
        logger.error(f"Error in pixi_project_status: {e}")
        return {
            "is_pixi_project": False,
            "is_healthy": False,
            "issues": [f"Status check failed: {str(e)}"],
            "recommendations": ["Verify pixi installation and project configuration"],
            "error": str(e),
        }


# =============================================================================
# TIER 3: DEPENDENCY MANAGEMENT
# =============================================================================


@app.tool()
def pixi_add_dependency(
    package: str,
    channel: str | None = None,
    is_dev: bool = False,
    working_dir: str | None = None,
) -> dict[str, Any]:
    """
    Add a dependency to pixi project.
    Example: pixi_add_dependency("pytest", "conda-forge")

    Replaces: Bash("pixi add pytest")

    Provides safe dependency addition with channel specification and development
    dependency support, ensuring proper project configuration management.
    """
    try:
        return container.pixi_service.add_dependency(
            package, channel, is_dev, working_dir
        )
    except Exception as e:
        logger.error(f"Error in pixi_add_dependency: {e}")
        return {"success": False, "message": f"Failed to add dependency: {str(e)}"}


@app.tool()
def pixi_remove_dependency(
    package: str, is_dev: bool = False, working_dir: str | None = None
) -> dict[str, Any]:
    """
    Remove a dependency from pixi project.

    Provides safe dependency removal with proper error handling and project
    state validation, ensuring clean dependency management.
    """
    try:
        return container.pixi_service.remove_dependency(package, is_dev, working_dir)
    except Exception as e:
        logger.error(f"Error in pixi_remove_dependency: {e}")
        return {"success": False, "message": f"Failed to remove dependency: {str(e)}"}


@app.tool()
def pixi_list_dependencies(working_dir: str | None = None) -> dict[str, Any]:
    """
    List all project dependencies with versions.
    Returns: {"dependencies": {"python": "3.12.*", "pytest": "^7.0"}, "dev_dependencies": {...}}

    Essential for: Dependency analysis and project understanding

    Provides comprehensive dependency information including production and development
    dependencies, channels, and version specifications for project analysis.
    """
    try:
        return container.pixi_service.list_dependencies(working_dir)
    except Exception as e:
        logger.error(f"Error in pixi_list_dependencies: {e}")
        return {
            "dependencies": {},
            "dev_dependencies": {},
            "error": f"Dependencies listing failed: {str(e)}",
        }


# =============================================================================
# TIER 4: PROJECT INITIALIZATION
# =============================================================================


@app.tool()
def pixi_init(path: str, template: str | None = None) -> dict[str, Any]:
    """
    Initialize a new pixi project.

    Provides safe project initialization with optional template support,
    ensuring proper project structure and configuration setup.
    """
    try:
        return container.pixi_service.init_project(path, template)
    except Exception as e:
        logger.error(f"Error in pixi_init: {e}")
        return {
            "success": False,
            "message": f"Project initialization failed: {str(e)}",
            "project_path": path,
        }


# =============================================================================
# INFORMATION RESOURCES
# =============================================================================


@app.resource("pixi-shell://project")
def get_project_info() -> dict[str, Any]:
    """Get current project information."""
    try:
        return container.pixi_service.get_info()
    except Exception as e:
        logger.error(f"Error getting project info: {e}")
        return {"error": f"Failed to get project info: {str(e)}"}


@app.resource("pixi-shell://tasks")
def get_all_tasks() -> dict[str, Any]:
    """Get all available pixi tasks."""
    try:
        return container.pixi_service.list_tasks()
    except Exception as e:
        logger.error(f"Error getting tasks: {e}")
        return {"error": f"Failed to get tasks: {str(e)}"}


@app.resource("pixi-shell://health")
def get_server_health() -> dict[str, Any]:
    """Get pixi shell server health information."""
    try:
        status = container.pixi_service.get_project_status()

        # Add server-specific health info
        status["server_status"] = "running"
        status["mcp_version"] = "0.1.0"
        status["security_model"] = "pixi_validation"

        return status
    except Exception as e:
        logger.error(f"Error getting server health: {e}")
        return {
            "is_healthy": False,
            "server_status": "error",
            "error": f"Health check failed: {str(e)}",
        }


@app.resource("pixi-shell://dependencies")
def get_project_dependencies() -> dict[str, Any]:
    """Get project dependencies information."""
    try:
        return container.pixi_service.list_dependencies()
    except Exception as e:
        logger.error(f"Error getting dependencies: {e}")
        return {"error": f"Failed to get dependencies: {str(e)}"}


# =============================================================================
# APPLICATION ENTRY POINT
# =============================================================================


def main():
    """Main entry point for the MCP server."""
    import sys
    import argparse
    import os

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Pixi Shell MCP Server")
    parser.add_argument(
        "--repository",
        type=str,
        help="Working directory/repository path for pixi operations",
    )
    args, unknown = parser.parse_known_args()

    # Set working directory if provided
    if args.repository:
        if os.path.exists(args.repository):
            os.chdir(args.repository)
            logger.info("Changed working directory to: %s", args.repository)
        else:
            logger.warning("Repository path does not exist: %s", args.repository)

    # Check if we're running in test mode
    if "pytest" in sys.modules or "test" in sys.argv:
        logger.info("Running in test mode")

    logger.info("Pixi Shell MCP Server starting...")
    logger.info("Working directory: %s", os.getcwd())

    # Validate pixi installation
    try:
        status = container.pixi_service.get_project_status()
        if status.get("pixi_executable_found", False):
            logger.info("Pixi executable found and available")
        else:
            logger.warning(
                "Pixi executable not found - install pixi for full functionality"
            )

        if status.get("is_pixi_project", False):
            logger.info("Running in pixi project directory")
            tasks = container.pixi_service.list_tasks()
            task_count = len(tasks.get("tasks", {}))
            logger.info("Available pixi tasks: %d", task_count)
        else:
            logger.info(
                "Not in a pixi project directory - project commands will require path specification"
            )

    except Exception as e:
        logger.error("Failed to perform initial pixi check: %s", e)
        # Continue anyway - some functions might still work

    logger.info("Pixi Shell MCP Server ready for secure task execution")
    logger.info("Security model: pixi task validation with argument sanitization")

    app.run()


if __name__ == "__main__":
    main()
