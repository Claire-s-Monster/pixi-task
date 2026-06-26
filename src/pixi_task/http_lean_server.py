#!/usr/bin/env python3
"""
Lean Pixi Shell MCP HTTP Server

HTTP transport entry point for the pixi-task MCP server.
Uses the lean 3-meta-tool pattern with SSE transport for Claude Code compatibility.

Key Benefits:
- HTTP/SSE transport: works with Claude Code 'type: http' MCP configuration
- 95%+ context reduction via lean meta-tool pattern
- GET /mcp: SSE heartbeat endpoint (prevents 'Failed to reconnect' errors)
- POST /mcp: JSON-RPC 2.0 tool execution
- GET /health: Server health monitoring

Usage:
    python -m pixi_task.http_lean_server --port 4300
    python -m pixi_task.http_lean_server --repository /path/to/project --port 4300

MCP Client Configuration (.mcp.json):
    {
      "pixi-bash": {
        "type": "http",
        "url": "http://127.0.0.1:4300/mcp",
        "transport": "sse"
      }
    }
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure the src directory is in the path for imports
src_dir = Path(__file__).parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("pixi_task.http_lean_server")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Lean Pixi Shell MCP HTTP Server - SSE transport with 95% context reduction"
    )
    parser.add_argument(
        "--repository",
        "--cwd",
        type=str,
        help="Working directory / repository path for pixi operations",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=4101,
        help="Port to listen on (default: 4300)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level",
    )
    return parser.parse_args()


def setup_logging(log_level: str) -> None:
    """Configure logging."""
    logging.getLogger().setLevel(getattr(logging, log_level))
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.WARNING)


def main() -> None:
    """Main entry point for the HTTP lean MCP server."""
    args = parse_args()
    setup_logging(args.log_level)

    # Resolve working directory. We do NOT os.chdir: the server process CWD is
    # unrelated to the caller's project. The repository becomes the resolver
    # base inside the service container (passed via working_dir below).
    working_dir = None
    if args.repository:
        repo_path = Path(args.repository).resolve()
        if not repo_path.exists():
            logger.error("Repository path does not exist: %s", repo_path)
            sys.exit(1)
        working_dir = str(repo_path)
        logger.info("Project base set to: %s", working_dir)

    logger.info("=" * 70)
    logger.info("LEAN PIXI SHELL MCP HTTP SERVER")
    logger.info("Transport: HTTP/SSE | Context: ~500 tokens (95%+ reduction)")
    logger.info("=" * 70)
    logger.info("Endpoints:")
    logger.info(
        "  GET  http://%s:%d/mcp  (SSE stream, keepalive)", args.host, args.port
    )
    logger.info(
        "  POST http://%s:%d/mcp  (JSON-RPC 2.0 tool calls)", args.host, args.port
    )
    logger.info("  GET  http://%s:%d/health", args.host, args.port)
    logger.info("")
    logger.info("MCP Client Configuration (.mcp.json):")
    logger.info('  "pixi-bash": {')
    logger.info('    "type": "http",')
    logger.info('    "url": "http://%s:%d/mcp",', args.host, args.port)
    logger.info('    "transport": "sse"')
    logger.info("  }")
    logger.info("")

    from pixi_task.http_server import HTTPPixiShellServer

    server = HTTPPixiShellServer(
        host=args.host,
        port=args.port,
        working_dir=working_dir,
    )

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")


if __name__ == "__main__":
    main()
