"""Regression tests for issue #33: tool calls blocked the HTTP event loop.

handle_mcp_post is ``async def`` but used to call the tool synchronously, so a
long subprocess.run froze the single uvicorn loop and every other request
(including /health) waited behind it.
"""

from __future__ import annotations

import asyncio
import threading

import httpx

from pixi_task.http_server import HTTPPixiShellServer

# Upper bound for the slow tool. Only reached on regression: pre-fix the loop is
# frozen, so nothing can set the release event and the tool times out instead.
SLOW_TOOL_TIMEOUT = 3.0


async def test_health_responds_while_tool_call_in_flight(tmp_path):
    server = HTTPPixiShellServer(working_dir=str(tmp_path))
    started = threading.Event()
    release = threading.Event()
    outcome: dict[str, bool] = {}

    def slow_tool(tool_name, arguments):
        started.set()
        outcome["released"] = release.wait(timeout=SLOW_TOOL_TIMEOUT)
        return {"ok": True}

    server._execute_lean_tool = slow_tool

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        call = asyncio.create_task(
            client.post(
                "/mcp",
                headers={"MCP-Session-Id": "mcp-test"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "server_info", "arguments": {}},
                },
            )
        )

        # Poll instead of blocking on the event so the loop stays free.
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set(), "tool call never started"

        health = await asyncio.wait_for(client.get("/health"), timeout=SLOW_TOOL_TIMEOUT + 2)
        assert health.status_code == 200

        # Release only after /health answered; a blocked loop never gets here in time.
        release.set()
        response = await asyncio.wait_for(call, timeout=SLOW_TOOL_TIMEOUT + 2)

    assert response.status_code == 200
    assert outcome["released"], "/health was served only after the slow tool timed out"
