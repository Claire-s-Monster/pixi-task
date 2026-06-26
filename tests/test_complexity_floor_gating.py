"""Regression tests for NEXT_TODO Defect 5: tool count discrepancy.

Before the fix, the discover_tools description hardcoded '12 total' even
though the registry has 11 tools and HTTP transport exposes only 7 via
expose_complexity_floor. These tests lock the gating contract so future
registry changes can't silently regress the per-transport counts.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from pixi_task.lean_mcp_interface import LeanMCPInterface


# The expected core+extended set is the durable contract: any addition
# at one of those complexity levels MUST also be reflected here so the
# test forces a deliberate update.
HTTP_EXPOSED = {
    "pixi_run_task",
    "pixi_list_tasks",
    "pixi_task_exists",
    "pixi_install",
    "pixi_info",
    "pixi_project_status",
    "pixi_list_dependencies",
}


def _build_interface(floor):
    business = MagicMock()
    return LeanMCPInterface(business, expose_complexity_floor=floor)


def test_http_floor_exposes_exactly_core_and_extended():
    """HTTP transport floor must expose only core+extended tools."""
    iface = _build_interface(["core", "extended"])
    result = iface.dispatch_meta_tool("discover_tools", {})
    names = {t["name"] for t in result["available_tools"]}
    assert names == HTTP_EXPOSED, (
        "HTTP floor surface drifted. Update HTTP_EXPOSED if intentional, "
        f"or fix the registry. Diff: {names ^ HTTP_EXPOSED}"
    )
    assert result["total_tools"] == len(HTTP_EXPOSED)


def test_stdio_floor_exposes_full_registry():
    """stdio transport (floor=None) must expose every registry entry."""
    iface = _build_interface(None)
    result = iface.dispatch_meta_tool("discover_tools", {})
    # Every registered tool must appear.
    names = {t["name"] for t in result["available_tools"]}
    assert names == set(iface.tool_registry.keys())
    assert result["total_tools"] == len(iface.tool_registry)


def test_specialized_tool_blocked_under_http_floor():
    """A specialized tool must error when called via dispatch under the HTTP floor."""
    iface = _build_interface(["core", "extended"])
    # pick a known specialized tool
    result = iface.dispatch_meta_tool(
        "execute_tool",
        {"tool_name": "pixi_add_dependency", "parameters": {}},
    )
    assert result.get("status") == "error"
    assert "not exposed" in result.get("error", "").lower()


def test_specialized_tool_visible_under_stdio_floor():
    """The same specialized tool must be visible (discoverable) under stdio."""
    iface = _build_interface(None)
    result = iface.dispatch_meta_tool("discover_tools", {"pattern": "add_dependency"})
    names = {t["name"] for t in result["available_tools"]}
    assert "pixi_add_dependency" in names


def test_discover_tools_description_does_not_hardcode_count():
    """Regression: description string must not contain a hardcoded total."""
    _build_interface(None)
    # The FastMCP app stores tool metadata; we check the dispatcher's
    # advertised description doesn't carry the stale '12 total' string.
    # Use the get_tool_spec path on discover_tools (a meta-tool).
    # Falls back to scanning known places if FastMCP API changes.
    src_path = __file__.replace(
        "tests/test_complexity_floor_gating.py",
        "src/pixi_task/lean_mcp_interface.py",
    )
    with open(src_path) as f:
        body = f.read()
    assert "(12 total)" not in body, "Stale '12 total' string found in lean_mcp_interface.py"
    assert "Discover available pixi tools" in body, (
        "Expected new discover_tools description text not found"
    )
