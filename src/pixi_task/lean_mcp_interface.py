#!/usr/bin/env python3
"""
Lean MCP Interface for Pixi Shell Server

Implements the revolutionary meta-tool pattern that reduces context consumption
from 20-50K tokens to ~500 tokens while maintaining 100% functionality through
dynamic discovery.

Key Architecture:
- 4 meta-tools: discover_tools, get_tool_spec, execute_tool, server_info
- Dynamic tool registry with comprehensive metadata
- Token limiting and intelligent response optimization
- Zero functionality loss compared to traditional MCP
- 95%+ reduction in context consumption

Context Impact:
- Traditional MCP: ~20-50K tokens for 11 tools
- Lean MCP: ~500 tokens for 4 meta-tools
- Savings: 95%+ reduction enabling 10+ MCP servers without context saturation

Business Logic:
- All existing pixi-task functionality preserved
- Same Container/DI pattern for consistency
- Enhanced with discovery metadata and optimization
"""

import json
import logging
from functools import wraps
from typing import Any, Dict

from fastmcp import FastMCP

from core.container import Container

logger = logging.getLogger("pixi_task.lean_mcp_interface")


class LeanMCPInterface:
    """
    Lean MCP Interface implementing the meta-tool pattern.

    Reduces context consumption from 20-50K tokens to ~500 tokens
    while maintaining 100% functionality through dynamic discovery.
    Exposes 4 meta-tools: discover_tools, get_tool_spec, execute_tool,
    server_info.
    """

    def __init__(
        self,
        business_engine: Container,
        expose_complexity_floor: list[str] | None = None,
        transport: str = "stdio",
    ):
        """Initialize lean interface with business logic container.

        Args:
            business_engine: DI container holding pixi-task service implementations.
            expose_complexity_floor: Restrict surface to tools whose
                complexity field is in this list. Pass None to expose every
                tool in the registry (stdio default). Pass ["core", "extended"]
                to gate out specialized tools (HTTP default — see http_server.py).
            transport: Transport label exposed via the server_info meta-tool
                so debugging clients can tell stdio vs http instances apart.
                Defaults to "stdio"; the HTTP entry point passes "http".
        """
        self.business_engine = business_engine
        self.expose_complexity_floor = expose_complexity_floor
        self.transport = transport
        self.app = FastMCP("pixi-task-lean", version="0.1.0")

        # Tool registry: maps tool names to implementations and metadata
        self.tool_registry = self._build_tool_registry()

        # Setup the 4 meta-tools
        self._setup_meta_tools()

        logger.info("Lean MCP Interface initialized with %d tools", len(self.tool_registry))
        logger.info("Context consumption: ~500 tokens (vs 20-50K for traditional MCP)")

    def _build_tool_registry(self) -> Dict[str, Dict[str, Any]]:
        """
        Build comprehensive tool registry with metadata for dynamic discovery.

        Each tool entry contains:
        - implementation: The actual function
        - schema: Full parameter schema
        - domain: Tool domain (task, environment, dependency, project)
        - complexity: Tool complexity (core, extended, specialized)
        - description: Brief description
        - examples: Usage examples
        """
        registry = {}

        # TIER 1: CORE TASK EXECUTION FUNCTIONS
        registry["pixi_run_task"] = {
            "implementation": self._wrap_tool(self._pixi_run_task_impl),
            "description": "Execute a pixi task with arguments (replaces Bash('pixi run ...'))",
            "domain": "task",
            "complexity": "core",
            "schema": {
                "type": "object",
                "properties": {
                    "task_name": {
                        "type": "string",
                        "description": "Name of the pixi task to execute",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": "Arguments to pass to the task",
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    },
                    "environment": {
                        "type": "string",
                        "description": "Pixi environment to run the task in (e.g. 'default', 'test', 'docs')",
                    },
                    "manifest_path": {
                        "type": "string",
                        "description": "Path to parent project's pixi.toml (for sub-packages that share a parent's pixi environment)",
                    },
                    "timeout": {
                        "type": "integer",
                        "default": 300,
                        "description": "Timeout in seconds",
                    },
                    "background": {
                        "type": "boolean",
                        "default": False,
                        "description": "Run the task detached in the background and return a job_id immediately instead of blocking. Use for long-running tasks (e.g. a full pytest suite) that exceed the MCP transport window. Poll results with pixi_task_status(job_id) or read the returned output_file.",
                    },
                    "output_file": {
                        "type": "string",
                        "description": "When background=true, write combined stdout/stderr to this path. Defaults to an auto-generated per-job log file whose path is returned in the response.",
                    },
                },
                "required": ["task_name"],
            },
            "examples": [
                {"task_name": "test"},
                {"task_name": "lint", "args": ["--fix"]},
                {"task_name": "test", "environment": "test"},
                {"task_name": "build", "timeout": 600},
                {"task_name": "test", "environment": "ci", "background": True},
            ],
        }

        registry["pixi_task_status"] = {
            "implementation": self._wrap_tool(self._pixi_task_status_impl),
            "description": "Check the status and output of a background pixi task launched via pixi_run_task(background=true)",
            "domain": "task",
            "complexity": "core",
            "schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job id returned by pixi_run_task(background=true)",
                    },
                    "tail_lines": {
                        "type": "integer",
                        "default": 50,
                        "description": "Number of trailing output lines to include (0 = full output)",
                    },
                },
                "required": ["job_id"],
            },
            "examples": [
                {"job_id": "a1b2c3d4e5f6"},
                {"job_id": "a1b2c3d4e5f6", "tail_lines": 200},
            ],
        }

        registry["pixi_list_tasks"] = {
            "implementation": self._wrap_tool(self._pixi_list_tasks_impl),
            "description": "List all available pixi tasks with descriptions",
            "domain": "task",
            "complexity": "core",
            "schema": {
                "type": "object",
                "properties": {
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    },
                    "environment": {
                        "type": "string",
                        "description": "Pixi environment name. None (default) lists tasks from base + all features. 'default' lists base [tasks] only. A named env walks [environments.<name>.features].",
                    },
                },
            },
            "examples": [
                {},
                {"working_dir": "/path/to/project"},
                {"environment": "ci"},
            ],
        }

        registry["pixi_task_exists"] = {
            "implementation": self._wrap_tool(self._pixi_task_exists_impl),
            "description": "Check if a pixi task exists before attempting to run it",
            "domain": "task",
            "complexity": "core",
            "schema": {
                "type": "object",
                "properties": {
                    "task_name": {
                        "type": "string",
                        "description": "Name of the task to check",
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    },
                    "environment": {
                        "type": "string",
                        "description": "Pixi environment name. None (default) lists tasks from base + all features. 'default' lists base [tasks] only. A named env walks [environments.<name>.features].",
                    },
                },
                "required": ["task_name"],
            },
            "examples": [
                {"task_name": "test"},
                {"task_name": "deploy", "working_dir": "/project"},
                {"task_name": "test", "environment": "ci"},
            ],
        }

        registry["pixi_install"] = {
            "implementation": self._wrap_tool(self._pixi_install_impl),
            "description": "Install/sync pixi environment and dependencies",
            "domain": "environment",
            "complexity": "extended",
            "schema": {
                "type": "object",
                "properties": {
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    },
                    "environment": {
                        "type": "string",
                        "description": "Pixi environment to install/sync (e.g. 'default', 'ci', 'docs'). When omitted, pixi installs the default environment only.",
                    },
                },
            },
            "examples": [
                {},
                {"working_dir": "/path/to/project"},
                {"environment": "ci"},
            ],
        }

        # TIER 2: ENVIRONMENT AND PROJECT MANAGEMENT
        registry["pixi_info"] = {
            "implementation": self._wrap_tool(self._pixi_info_impl),
            "description": "Get pixi project information and environment status",
            "domain": "environment",
            "complexity": "extended",
            "schema": {
                "type": "object",
                "properties": {
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    }
                },
            },
            "examples": [{}],
        }

        registry["pixi_project_status"] = {
            "implementation": self._wrap_tool(self._pixi_project_status_impl),
            "description": "Get comprehensive project status and health check",
            "domain": "project",
            "complexity": "extended",
            "schema": {
                "type": "object",
                "properties": {
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    }
                },
            },
            "examples": [{}],
        }

        # TIER 3: DEPENDENCY MANAGEMENT
        registry["pixi_add_dependency"] = {
            "implementation": self._wrap_tool(self._pixi_add_dependency_impl),
            "description": "Add a dependency to pixi project",
            "domain": "dependency",
            "complexity": "specialized",
            "schema": {
                "type": "object",
                "properties": {
                    "package": {"type": "string", "description": "Package name to add"},
                    "channel": {
                        "type": "string",
                        "description": "Conda channel (optional)",
                    },
                    "is_dev": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether this is a development dependency",
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    },
                },
                "required": ["package"],
            },
            "examples": [
                {"package": "pytest"},
                {"package": "ruff", "channel": "conda-forge", "is_dev": True},
            ],
        }

        registry["pixi_remove_dependency"] = {
            "implementation": self._wrap_tool(self._pixi_remove_dependency_impl),
            "description": "Remove a dependency from pixi project",
            "domain": "dependency",
            "complexity": "specialized",
            "schema": {
                "type": "object",
                "properties": {
                    "package": {
                        "type": "string",
                        "description": "Package name to remove",
                    },
                    "is_dev": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether this is a development dependency",
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    },
                },
                "required": ["package"],
            },
            "examples": [{"package": "pytest"}, {"package": "black", "is_dev": True}],
        }

        registry["pixi_list_dependencies"] = {
            "implementation": self._wrap_tool(self._pixi_list_dependencies_impl),
            "description": "List all project dependencies with versions",
            "domain": "dependency",
            "complexity": "extended",
            "schema": {
                "type": "object",
                "properties": {
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    }
                },
            },
            "examples": [{}],
        }

        # TIER 4: PROJECT INITIALIZATION
        registry["pixi_init"] = {
            "implementation": self._wrap_tool(self._pixi_init_impl),
            "description": "Initialize a new pixi project",
            "domain": "project",
            "complexity": "specialized",
            "schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path where to initialize the project",
                    },
                    "template": {
                        "type": "string",
                        "description": "Template to use (optional)",
                    },
                },
                "required": ["path"],
            },
            "examples": [
                {"path": "./new-project"},
                {"path": "./ml-project", "template": "python-ml"},
            ],
        }

        # TIER 5: CONDA PACKAGE BUILD
        registry["rattler_build_smart"] = {
            "implementation": self._wrap_tool(self._rattler_build_smart_impl),
            "description": "Run rattler-build with smart output summarization (errors, warnings, packages built)",
            "domain": "build",
            "complexity": "specialized",
            "schema": {
                "type": "object",
                "properties": {
                    "recipe_path": {
                        "type": "string",
                        "default": ".",
                        "description": "Path to recipe.yaml or directory containing it",
                    },
                    "target_platform": {
                        "type": "string",
                        "description": "Target platform (e.g., 'linux-64', 'osx-arm64', 'win-64')",
                    },
                    "channels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Channels to search for dependencies",
                    },
                    "variant_config": {
                        "type": "string",
                        "description": "Path to variant configuration file (variants.yaml)",
                    },
                    "variants": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": 'Variant overrides as key-value pairs (e.g., {"python": "3.12"})',
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory for the build",
                    },
                    "timeout": {
                        "type": "integer",
                        "default": 1800,
                        "description": "Build timeout in seconds (default: 30 minutes)",
                    },
                },
            },
            "examples": [
                {"recipe_path": "."},
                {"recipe_path": "./recipe", "target_platform": "linux-64"},
                {
                    "recipe_path": ".",
                    "channels": ["conda-forge"],
                    "variants": {"python": "3.12"},
                },
                {
                    "recipe_path": "./recipe.yaml",
                    "variant_config": "./variants.yaml",
                    "timeout": 3600,
                },
            ],
        }

        return registry

    def _wrap_tool(self, tool_func):
        """Wrap tool function with token limiting and error handling."""

        @wraps(tool_func)
        def wrapper(*args, **kwargs):
            try:
                result = tool_func(*args, **kwargs)
                return apply_token_limits(result, tool_func.__name__)
            except Exception as e:
                logger.error(f"Error in {tool_func.__name__}: {e}")
                return {"error": str(e), "tool": tool_func.__name__}

        return wrapper

    def dispatch_meta_tool(self, name: str, params: dict) -> dict:
        """
        Single dispatch entry point for the three meta-tools.

        Used both by the FastMCP closures registered in _setup_meta_tools
        and by transport adapters (e.g., HTTPServer) that need to invoke
        meta-tool behavior without going through the FastMCP protocol layer.

        name must be one of: "discover_tools", "get_tool_spec", "execute_tool",
        "server_info".
        """
        if name == "discover_tools":
            pattern = params.get("pattern", "")

            exposed_items = [
                (name_, info)
                for name_, info in self.tool_registry.items()
                if self.expose_complexity_floor is None
                or info.get("complexity") in self.expose_complexity_floor
            ]

            tools = []
            for tool_name, info in exposed_items:
                if pattern and pattern.strip() and pattern.lower() not in tool_name.lower():
                    continue

                tools.append(
                    {
                        "name": tool_name,
                        "description": info["description"],
                        "domain": info["domain"],
                        "complexity": info["complexity"],
                    }
                )

            return {
                "available_tools": tools,
                "total_tools": len(exposed_items),
                "filtered_count": len(tools),
                "domains": list(set(info["domain"] for _, info in exposed_items)),
                "complexity_levels": list(set(info["complexity"] for _, info in exposed_items)),
            }

        if name == "get_tool_spec":
            tool_name = params.get("tool_name") or ""
            if tool_name not in self.tool_registry or (
                self.expose_complexity_floor is not None
                and self.tool_registry[tool_name]["complexity"] not in self.expose_complexity_floor
            ):
                exposed = [
                    n
                    for n, info in self.tool_registry.items()
                    if self.expose_complexity_floor is None
                    or info["complexity"] in self.expose_complexity_floor
                ]
                return {
                    "error": f"Tool '{tool_name}' not found",
                    "available_tools": exposed,
                }

            tool_info = self.tool_registry[tool_name]
            return {
                "name": tool_name,
                "description": tool_info["description"],
                "domain": tool_info["domain"],
                "complexity": tool_info["complexity"],
                "schema": tool_info["schema"],
                "examples": tool_info["examples"],
            }

        if name == "execute_tool":
            tool_name = params.get("tool_name") or ""
            parameters = params.get("parameters", {})

            if tool_name not in self.tool_registry:
                exposed_names = [
                    n
                    for n, info in self.tool_registry.items()
                    if self.expose_complexity_floor is None
                    or info.get("complexity") in self.expose_complexity_floor
                ]
                return {
                    "tool": tool_name,
                    "status": "error",
                    "error": f"Tool '{tool_name}' not found",
                    "available_tools": exposed_names,
                }

            if (
                self.expose_complexity_floor is not None
                and self.tool_registry[tool_name]["complexity"] not in self.expose_complexity_floor
            ):
                return {
                    "tool": tool_name,
                    "status": "error",
                    "error": f"Tool '{tool_name}' is not exposed on this transport",
                }

            tool_func = self.tool_registry[tool_name]["implementation"]

            if isinstance(parameters, str):
                try:
                    parameters = json.loads(parameters)
                except (json.JSONDecodeError, TypeError) as e:
                    return {
                        "tool": tool_name,
                        "status": "error",
                        "error": f"Invalid parameters JSON: {e}",
                    }
            if not isinstance(parameters, dict):
                return {
                    "tool": tool_name,
                    "status": "error",
                    "error": (f"parameters must be a mapping, got {type(parameters).__name__}"),
                }

            try:
                result = tool_func(**parameters)
                return {"tool": tool_name, "status": "success", "result": result}
            except Exception as e:
                logger.error(f"Error executing {tool_name}: {e}")
                return {"tool": tool_name, "status": "error", "error": str(e)}

        if name == "server_info":
            return self._server_info_impl()

        return {
            "error": f"Unknown meta-tool: {name}",
            "available_meta_tools": [
                "discover_tools",
                "get_tool_spec",
                "execute_tool",
                "server_info",
            ],
        }

    def _setup_meta_tools(self):
        """Setup the 4 meta-tools for dynamic discovery."""

        @self.app.tool(
            description=(
                "Discover available pixi tools (count varies by transport). "
                "USE WHEN: running pixi tasks, managing dependencies, checking project status. "
                "Returns total_tools and filtered_count in the response — those are the live counts."
            )
        )
        def discover_tools(pattern: str = "") -> Dict[str, Any]:
            """
            [STEP 1] Get available pixi-task tools with minimal context consumption.

            USE WHEN:
            - Starting work on a pixi-managed Python project
            - Need to run tests, lint, or other pixi tasks
            - Managing project dependencies (add/remove packages)
            - Checking pixi environment status
            - Building conda packages with rattler-build

            COMMON TASKS:
            - Run tests: pixi_run_task(task_name="test")
            - Lint code: pixi_run_task(task_name="lint")
            - Add package: pixi_add_dependency(package="pytest")
            - Check status: pixi_project_status()

            WORKFLOW:
            1. discover_tools() → Find available tools
            2. get_tool_spec(name) → Get parameters for specific tool
            3. execute_tool(name, params) → Run the tool

            Args:
                pattern: Filter by name pattern (substring match). Try "task", "dependency", "build"

            Returns:
                {
                    "available_tools": [...],
                    "total_tools": <n>,  # depends on transport
                    "domains": ["task", "environment", "dependency", "project", "build"]
                }

                The set of exposed tools is determined by expose_complexity_floor on this
                interface; HTTP transport currently exposes 'core' and 'extended', stdio
                exposes everything.

            Examples:
                - discover_tools() → List all exposed tools (transport-filtered)
                - discover_tools("task") → Filter task-related tools
                - discover_tools("dependency") → Filter dependency management tools
            """
            return self.dispatch_meta_tool("discover_tools", {"pattern": pattern})

        @self.app.tool(
            description="Get pixi-task tool specification with schema and examples. USE WHEN: need parameter details before executing a tool"
        )
        def get_tool_spec(tool_name: str) -> Dict[str, Any]:
            """
            [STEP 2] Get full specification for specific pixi-task tool.

            DON'T SKIP THIS STEP! Get the schema before calling execute_tool()
            to understand required/optional parameters and see usage examples.

            USE WHEN:
            - About to run a tool and need parameter schema
            - Unsure about required vs optional parameters
            - Need working_dir or timeout parameter details
            - Want to see usage examples

            WORKFLOW:
            1. discover_tools() → Found "pixi_run_task"
            2. get_tool_spec("pixi_run_task") → Get parameters ← YOU ARE HERE
            3. execute_tool("pixi_run_task", {...}) → Run with correct params

            Args:
                tool_name: Exact tool name from discover_tools() result.
                    Common tools: pixi_run_task, pixi_list_tasks, pixi_add_dependency,
                    pixi_project_status, rattler_build_smart

            Returns:
                {
                    "name": "pixi_run_task",
                    "description": "...",
                    "schema": {"properties": {...}, "required": [...]},
                    "examples": [{"task_name": "test"}, ...]
                }

            TOOL NOT FOUND? Run discover_tools() first to see available tools.
            """
            return self.dispatch_meta_tool("get_tool_spec", {"tool_name": tool_name})

        @self.app.tool(
            description="Execute pixi-task tool with parameters. USE WHEN: running pixi tasks, managing dependencies, building packages"
        )
        def execute_tool(tool_name: str, parameters: Dict[str, Any] | str) -> Dict[str, Any]:
            """
            [STEP 3] Execute pixi-task tool with parameters using dynamic dispatch.

            USE WHEN:
            - Running pixi tasks (test, lint, build, etc.)
            - Managing dependencies (add/remove packages)
            - Checking project status
            - Building conda packages with rattler-build

            WORKFLOW:
            1. discover_tools() → Found available tools
            2. get_tool_spec(name) → Got parameter schema
            3. execute_tool(name, params) → Execute the tool ← YOU ARE HERE

            COMMON OPERATIONS:
            - Run tests: execute_tool("pixi_run_task", {"task_name": "test"})
            - Run lint: execute_tool("pixi_run_task", {"task_name": "lint"})
            - Add package: execute_tool("pixi_add_dependency", {"package": "pytest"})
            - Project status: execute_tool("pixi_project_status", {})
            - Build package: execute_tool("rattler_build_smart", {"recipe_path": "."})

            Args:
                tool_name: Exact tool name from discover_tools()
                parameters: Tool parameters as JSON object. Get schema via get_tool_spec()

            Returns:
                {
                    "tool": "pixi_run_task",
                    "status": "success",
                    "result": {...task output...}
                }

            ERROR RESPONSE:
                {"tool": "...", "status": "error", "error": "error message"}

            DON'T KNOW PARAMETERS? Run get_tool_spec(tool_name) first.
            """
            return self.dispatch_meta_tool(
                "execute_tool", {"tool_name": tool_name, "parameters": parameters}
            )

        @self.app.tool(
            description=(
                "Return server self-identification: name, version, source URLs, "
                "transport label, and live tool counts. "
                "USE WHEN: filing bug reports, debugging which instance you reached, "
                "or fingerprinting the server version."
            )
        )
        def server_info() -> dict[str, Any]:
            """Return server metadata for clients and harnesses."""
            return self._server_info_impl()

    def get_app(self) -> FastMCP:
        """Get the FastMCP application instance."""
        return self.app

    # Implementation methods that delegate to business engine
    def _pixi_run_task_impl(
        self,
        task_name: str,
        args: list[str] = [],
        working_dir: str | None = None,
        environment: str | None = None,
        manifest_path: str | None = None,
        timeout: int = 300,
        background: bool = False,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        if background:
            return self.business_engine.pixi_service.run_task_background(
                task_name,
                args,
                working_dir,
                environment=environment,
                manifest_path=manifest_path,
                output_file=output_file,
            )
        return self.business_engine.pixi_service.run_task(
            task_name,
            args,
            working_dir,
            timeout,
            environment=environment,
            manifest_path=manifest_path,
        )

    def _pixi_task_status_impl(
        self,
        job_id: str,
        tail_lines: int = 50,
    ) -> dict[str, Any]:
        return self.business_engine.pixi_service.get_job_status(job_id, tail_lines)

    def _pixi_list_tasks_impl(
        self,
        working_dir: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.business_engine.pixi_service.list_tasks(working_dir, environment=environment)

    def _pixi_task_exists_impl(
        self,
        task_name: str,
        working_dir: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        exists = self.business_engine.pixi_service.task_exists(
            task_name, working_dir, environment=environment
        )
        return {
            "exists": exists,
            "task_name": task_name,
            "working_dir": working_dir or "current",
            "environment": environment,
        }

    def _pixi_install_impl(
        self,
        working_dir: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.business_engine.pixi_service.install(working_dir, environment=environment)

    def _pixi_info_impl(self, working_dir: str | None = None) -> dict[str, Any]:
        return self.business_engine.pixi_service.get_info(working_dir)

    def _pixi_project_status_impl(self, working_dir: str | None = None) -> dict[str, Any]:
        return self.business_engine.pixi_service.get_project_status(working_dir)

    def _pixi_add_dependency_impl(
        self,
        package: str,
        channel: str | None = None,
        is_dev: bool = False,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        return self.business_engine.pixi_service.add_dependency(
            package, channel, is_dev, working_dir
        )

    def _pixi_remove_dependency_impl(
        self, package: str, is_dev: bool = False, working_dir: str | None = None
    ) -> dict[str, Any]:
        return self.business_engine.pixi_service.remove_dependency(package, is_dev, working_dir)

    def _pixi_list_dependencies_impl(self, working_dir: str | None = None) -> dict[str, Any]:
        return self.business_engine.pixi_service.list_dependencies(working_dir)

    def _pixi_init_impl(self, path: str, template: str | None = None) -> dict[str, Any]:
        return self.business_engine.pixi_service.init_project(path, template)

    def _server_info_impl(self) -> dict[str, Any]:
        """Build the server_info response payload.

        Surfaces enough metadata for clients to self-identify the server
        and route bug reports without external lookup.
        """
        try:
            from importlib.metadata import version as _pkg_version

            pkg_version = _pkg_version("pixi-task")
        except Exception:
            pkg_version = "0.1.0"

        exposed = [
            name
            for name, info in self.tool_registry.items()
            if self.expose_complexity_floor is None
            or info.get("complexity") in self.expose_complexity_floor
        ]

        return {
            "name": "pixi-task",
            "version": pkg_version,
            "description": (
                "A secure MCP server providing controlled access to pixi tasks "
                "and commands, eliminating agent bash circumvention."
            ),
            "source_url": "https://github.com/MementoRC/pixi-task",
            "issues_url": "https://github.com/MementoRC/pixi-task/issues",
            "transport": self.transport,
            "tool_count": len(exposed),
            "registry_size": len(self.tool_registry),
            "protocol_version": "2024-11-05",
        }

    def _rattler_build_smart_impl(
        self,
        recipe_path: str = ".",
        target_platform: str | None = None,
        channels: list[str] | None = None,
        variant_config: str | None = None,
        variants: dict[str, str] | None = None,
        working_dir: str | None = None,
        timeout: int = 1800,
    ) -> dict[str, Any]:
        return self.business_engine.pixi_service.rattler_build_smart(
            recipe_path=recipe_path,
            target_platform=target_platform,
            channels=channels,
            variant_config=variant_config,
            variants=variants,
            working_dir=working_dir,
            timeout=timeout,
        )


def apply_token_limits(result: Any, tool_name: str) -> Any:
    """
    Apply intelligent token limits to tool responses.

    - Preserve critical information
    - Truncate verbose details
    - Add truncation indicators
    - Maintain JSON structure
    """
    MAX_TOKENS = 2000  # Conservative limit

    if isinstance(result, dict):
        serialized = json.dumps(result, indent=2)
        if len(serialized) <= MAX_TOKENS * 4:  # Rough token estimate (4 chars per token)
            return result

        # Intelligent truncation logic
        return truncate_intelligently(result, MAX_TOKENS, tool_name)

    return result


def truncate_intelligently(
    result: Dict[str, Any], max_tokens: int, tool_name: str
) -> Dict[str, Any]:
    """
    Intelligently truncate tool responses while preserving critical information.

    Priority order:
    1. Status/success indicators
    2. Error messages
    3. Core data (first few items)
    4. Metadata
    5. Verbose details (truncated)
    """
    # Always preserve these critical keys
    critical_keys = {
        "success",
        "error",
        "status",
        "exists",
        "is_pixi_project",
        "task_name",
        "tool",
    }
    preserved = {}

    # First pass: preserve critical information
    for key in critical_keys:
        if key in result:
            preserved[key] = result[key]

    # Second pass: add core data with limits

    for key, value in result.items():
        if key in critical_keys:
            continue

        if isinstance(value, dict) and len(value) > 10:
            # Truncate large dictionaries
            truncated = dict(list(value.items())[:5])
            truncated["_truncated"] = f"showing 5/{len(value)} items"
            preserved[key] = truncated
        elif isinstance(value, list) and len(value) > 10:
            # Truncate large lists
            preserved[key] = value[:5] + [f"_truncated: showing 5/{len(value)} items"]
        elif isinstance(value, str) and len(value) > 500:
            # Truncate long strings
            preserved[key] = value[:400] + f"... [truncated {len(value) - 400} chars]"
        else:
            preserved[key] = value

        # Check if we're approaching token limit
        current_size = len(json.dumps(preserved))
        if current_size > max_tokens * 3:  # Conservative check
            break

    preserved["_token_limited"] = f"Response optimized for context efficiency by {tool_name}"
    return preserved
