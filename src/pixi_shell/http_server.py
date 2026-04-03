"""
FastAPI HTTP Server for Pixi Shell MCP Server.

Implements the MCP HTTP transport with SSE (Server-Sent Events) for Claude Code
compatibility. Uses the lean 3-meta-tool pattern for minimal context consumption.

Key features:
- POST /mcp for JSON-RPC 2.0 client-to-server requests
- GET /mcp for SSE server-to-client notifications (keepalive)
- Session management with MCP-Session-Id header
- Localhost-only security by default
- Health check endpoint

Architecture:
    Claude Code MCP Client → HTTP GET /mcp (SSE stream, keepalive)
                           → HTTP POST /mcp (JSON-RPC 2.0 tool calls)
                           → pixi_shell LeanMCPInterface (3 meta-tools)
                           → PixiShellService → pixi commands
"""

import asyncio
import json
import logging
import secrets
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

__all__ = ["HTTPPixiShellServer"]


class HTTPPixiShellServer:
    """
    FastAPI HTTP server for Pixi Shell MCP operations.

    Provides HTTP endpoints implementing the MCP protocol over HTTP transport:
    - GET /mcp: SSE stream for server-to-client notifications (required for SSE transport)
    - POST /mcp: JSON-RPC 2.0 endpoint for client-to-server requests
    - GET /health: Health check endpoint

    Session management:
    - Sessions are created on initialize and tracked by MCP-Session-Id header
    - Simple in-memory session store (no persistence needed for stateless pixi ops)
    - Each session holds the working directory context

    Security:
    - Binds to localhost (127.0.0.1) by default
    - Session validation on all tool calls
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4101,
        working_dir: str | None = None,
        session_timeout: float = 3600.0,
    ):
        """
        Initialize HTTP Pixi Shell server.

        Args:
            host: Host address to bind to (default: 127.0.0.1)
            port: Port to listen on (default: 4300)
            working_dir: Default working directory for pixi operations
            session_timeout: Session timeout in seconds (default: 3600 = 1 hour)
        """
        self.host = host
        self.port = port
        self.working_dir = working_dir
        self.session_timeout = session_timeout

        # In-memory session store: session_id -> {created_at, last_activity, working_dir}
        self._sessions: dict[str, dict[str, Any]] = {}

        # Import here to avoid circular imports at module level
        from core.container import Container
        from pixi_shell.lean_mcp_interface import LeanMCPInterface

        self._container = Container(working_dir=working_dir)
        self._lean_interface = LeanMCPInterface(self._container)

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            logger.info("Pixi Shell HTTP MCP Server starting on %s:%d", host, port)
            logger.info("Working directory: %s", working_dir or "current")
            yield
            logger.info("Pixi Shell HTTP MCP Server shutting down")
            self._sessions.clear()

        self.app = FastAPI(
            title="Pixi Shell MCP HTTP Server",
            description="HTTP transport for pixi task execution via MCP protocol",
            version="0.1.0",
            lifespan=lifespan,
        )

        # CORS middleware for local development
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost",
                "http://127.0.0.1",
                "http://localhost:*",
                "http://127.0.0.1:*",
            ],
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["MCP-Session-Id", "MCP-Protocol-Version"],
        )

        self._register_endpoints()

    def _create_session(self, session_id: str | None = None) -> str:
        """Create a new session and return the session ID."""
        import time

        sid = session_id or f"mcp-{secrets.token_urlsafe(8)}"
        self._sessions[sid] = {
            "created_at": time.time(),
            "last_activity": time.time(),
            "working_dir": self.working_dir,
        }
        return sid

    def _validate_session(self, session_id: str) -> bool:
        """Check if a session exists and is still valid."""
        import time

        if session_id not in self._sessions:
            return False
        session = self._sessions[session_id]
        idle = time.time() - session["last_activity"]
        if idle > self.session_timeout:
            del self._sessions[session_id]
            return False
        return True

    def _touch_session(self, session_id: str) -> None:
        """Update session last activity timestamp."""
        import time

        if session_id in self._sessions:
            self._sessions[session_id]["last_activity"] = time.time()

    def _execute_lean_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Execute a lean meta-tool and return the raw result."""
        registry = self._lean_interface.tool_registry

        if tool_name == "discover_tools":
            pattern = arguments.get("pattern", "")
            tools = []
            for name, info in registry.items():
                if pattern and pattern.strip() and pattern.lower() not in name.lower():
                    continue
                tools.append(
                    {
                        "name": name,
                        "description": info["description"],
                        "domain": info["domain"],
                        "complexity": info["complexity"],
                    }
                )
            return {
                "available_tools": tools,
                "total_tools": len(registry),
                "filtered_count": len(tools),
                "domains": list(set(info["domain"] for info in registry.values())),
                "complexity_levels": list(
                    set(info["complexity"] for info in registry.values())
                ),
            }

        if tool_name == "get_tool_spec":
            target = arguments.get("tool_name")
            if not target or target not in registry:
                return {
                    "error": f"Tool '{target}' not found",
                    "available_tools": list(registry.keys()),
                }
            info = registry[target]
            return {
                "name": target,
                "description": info["description"],
                "domain": info["domain"],
                "complexity": info["complexity"],
                "schema": info["schema"],
                "examples": info["examples"],
            }

        if tool_name == "execute_tool":
            target = arguments.get("tool_name")
            params = arguments.get("parameters", {})
            if not target or target not in registry:
                return {
                    "error": f"Tool '{target}' not found",
                    "available_tools": list(registry.keys()),
                }
            impl = registry[target]["implementation"]
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except (json.JSONDecodeError, TypeError):
                    params = {}
            try:
                result = impl(**params)
                return {"tool": target, "status": "success", "result": result}
            except Exception as e:
                logger.error("Tool execution error for %s: %s", target, e)
                return {"tool": target, "status": "error", "error": str(e)}

        # Unknown meta-tool
        return {
            "error": f"Unknown meta-tool: {tool_name}",
            "available_meta_tools": ["discover_tools", "get_tool_spec", "execute_tool"],
        }

    def _register_endpoints(self) -> None:
        """Register all HTTP endpoints."""

        # OAuth/OIDC discovery stubs — Claude Code 2.1.84+ probes these
        # before connecting. Return 404 without JSON body so CC skips auth.
        @self.app.get("/.well-known/{path:path}")
        async def well_known_stub(path: str):
            return JSONResponse(status_code=404, content={"error": "OAuth not supported"})

        @self.app.post("/register")
        async def register_stub():
            return JSONResponse(status_code=404, content={"error": "Dynamic client registration not supported"})

        @self.app.get("/mcp")
        async def handle_mcp_sse(
            mcp_session_id: str | None = Header(None, alias="MCP-Session-Id"),
        ) -> StreamingResponse:
            """
            SSE endpoint for MCP server-to-client notifications.

            Required for SSE transport compatibility with Claude Code MCP clients.
            Without this GET endpoint, clients fail with 'Failed to reconnect'.
            Currently sends periodic heartbeat comments to keep the connection alive.
            """

            async def event_generator() -> AsyncGenerator[str, None]:
                try:
                    while True:
                        # Heartbeat comment - ignored by SSE clients but keeps connection alive
                        yield ": heartbeat\n\n"
                        await asyncio.sleep(30)
                except asyncio.CancelledError:
                    pass

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        @self.app.post("/mcp")
        async def handle_mcp_post(
            request: Request,
            mcp_session_id: str | None = Header(None, alias="MCP-Session-Id"),
        ) -> JSONResponse:
            """
            JSON-RPC 2.0 endpoint for MCP client-to-server requests.

            Handles the MCP protocol methods:
            - initialize: Creates session, returns MCP-Session-Id header
            - notifications/initialized: Acknowledges client ready
            - tools/list: Returns the 3 lean meta-tool definitions
            - tools/call: Executes a meta-tool (discover_tools, get_tool_spec, execute_tool)
            """
            # Parse request body
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    status_code=400,
                    content={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    },
                )

            method = body.get("method")
            params = body.get("params", {}) or {}
            req_id = body.get("id")
            jsonrpc_version = body.get("jsonrpc")

            if jsonrpc_version != "2.0":
                return JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32600,
                            "message": "Invalid Request - jsonrpc must be '2.0'",
                        },
                    }
                )

            # initialize - create new session
            if method == "initialize":
                new_session_id = self._create_session()
                logger.info("MCP session initialized: %s", new_session_id)
                response = JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "tools": {"listChanged": True},
                            },
                            "serverInfo": {
                                "name": "pixi-shell",
                                "version": "0.1.0",
                            },
                        },
                    }
                )
                response.headers["MCP-Session-Id"] = new_session_id
                response.headers["MCP-Protocol-Version"] = "2024-11-05"
                return response

            # notifications/initialized - acknowledge
            if method == "notifications/initialized":
                if mcp_session_id:
                    self._touch_session(mcp_session_id)
                return JSONResponse(
                    content={"jsonrpc": "2.0", "id": req_id, "result": {}}
                )

            # tools/list - return the 3 lean meta-tool definitions
            if method == "tools/list":
                if mcp_session_id:
                    self._touch_session(mcp_session_id)
                return JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "tools": [
                                {
                                    "name": "discover_tools",
                                    "description": (
                                        "Discover pixi environment management tools (12 total). "
                                        "USE WHEN: running pixi tasks, managing dependencies, "
                                        "checking project status, building conda packages."
                                    ),
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "pattern": {
                                                "type": "string",
                                                "default": "",
                                                "description": (
                                                    "Filter by name pattern (substring match). "
                                                    "Try 'task', 'dependency', 'build'"
                                                ),
                                            }
                                        },
                                    },
                                },
                                {
                                    "name": "get_tool_spec",
                                    "description": (
                                        "Get full specification for a pixi-shell tool "
                                        "including schema and examples. USE WHEN: need "
                                        "parameter details before executing a tool."
                                    ),
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "tool_name": {
                                                "type": "string",
                                                "description": (
                                                    "Exact tool name from discover_tools(). "
                                                    "Common: pixi_run_task, pixi_list_tasks, "
                                                    "pixi_add_dependency, pixi_project_status, "
                                                    "rattler_build_smart"
                                                ),
                                            }
                                        },
                                        "required": ["tool_name"],
                                    },
                                },
                                {
                                    "name": "execute_tool",
                                    "description": (
                                        "Execute a pixi-shell tool with parameters. "
                                        "USE WHEN: running pixi tasks, managing dependencies, "
                                        "building conda packages."
                                    ),
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "tool_name": {
                                                "type": "string",
                                                "description": "Exact tool name from discover_tools()",
                                            },
                                            "parameters": {
                                                "type": "object",
                                                "description": "Tool parameters. Get schema via get_tool_spec()",
                                            },
                                        },
                                        "required": ["tool_name", "parameters"],
                                    },
                                },
                            ]
                        },
                    }
                )

            # tools/call - execute a meta-tool
            if method == "tools/call":
                # Validate session
                if not mcp_session_id:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32600,
                                "message": "Missing MCP-Session-Id header",
                            },
                        },
                    )
                if not self._validate_session(mcp_session_id):
                    # Auto-recreate expired/unknown sessions — server is stateless
                    logger.info("Auto-recreating expired session: %s", mcp_session_id)
                    self._create_session(session_id=mcp_session_id)

                self._touch_session(mcp_session_id)

                # Extract tool name and arguments
                call_params = params or {}
                tool_name = call_params.get("name")
                arguments = call_params.get("arguments", {}) or {}

                if not tool_name:
                    return JSONResponse(
                        content={
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32602,
                                "message": "Invalid params - 'name' required",
                            },
                        }
                    )

                try:
                    result = self._execute_lean_tool(tool_name, arguments)
                    logger.debug(
                        "Meta-tool executed: %s (session: %s)",
                        tool_name,
                        mcp_session_id,
                    )

                    return JSONResponse(
                        content={
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [
                                    {"type": "text", "text": json.dumps(result)}
                                ]
                            },
                        }
                    )

                except Exception as e:
                    logger.error(
                        "Tool execution failed: %s: %s", tool_name, e, exc_info=True
                    )
                    return JSONResponse(
                        content={
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32603,
                                "message": f"Internal error: {e}",
                            },
                        }
                    )

            # Unknown method
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }
            )

        @self.app.get("/health")
        async def health_check() -> JSONResponse:
            """Health check endpoint."""
            return JSONResponse(
                content={
                    "status": "healthy",
                    "server": "pixi-shell",
                    "version": "0.1.0",
                    "active_sessions": len(self._sessions),
                    "working_dir": self.working_dir or "current",
                }
            )

    def run(self) -> None:
        """Run the HTTP server with uvicorn."""
        logger.info(
            "Starting Pixi Shell HTTP MCP Server on %s:%d", self.host, self.port
        )
        uvicorn.run(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
