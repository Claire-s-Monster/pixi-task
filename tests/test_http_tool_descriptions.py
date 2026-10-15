"""Regression tests for issue #45: HTTP tools/list hints named unexposed tools.

The hardcoded tools/list response advertised tool names (e.g. in the
get_tool_spec hint) that the HTTP transport's complexity floor does not expose,
so agents called them and got "not found".
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import httpx

from pixi_task.http_server import HTTPPixiShellServer
from pixi_task.lean_mcp_interface import LeanMCPInterface

TOOL_NAME_PATTERN = re.compile(r"\b(?:pixi|rattler|conda)_[a-z0-9_]+\b")


def _descriptions(node: Any) -> Iterator[str]:
    """Yield every string stored under a "description" key, recursively."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "description" and isinstance(value, str):
                yield value
            else:
                yield from _descriptions(value)
    elif isinstance(node, list):
        for item in node:
            yield from _descriptions(item)


async def test_tools_list_only_names_tools_exposed_over_http(tmp_path):
    server = HTTPPixiShellServer(working_dir=str(tmp_path))
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code == 200
    tools = response.json()["result"]["tools"]

    exposed_iface = LeanMCPInterface(MagicMock(), expose_complexity_floor=["core", "extended"])
    discovered = exposed_iface.dispatch_meta_tool("discover_tools", {})
    exposed = {t["name"] for t in discovered["available_tools"]}

    mentioned = {
        token for text in _descriptions(tools) for token in TOOL_NAME_PATTERN.findall(text)
    }
    offenders = sorted(mentioned - exposed)
    assert not offenders, (
        f"HTTP tools/list descriptions name tools not exposed over HTTP: {offenders}"
    )
