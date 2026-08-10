"""Regression tests for NEXT_TODO Defect 4: missing server_info meta-tool.

Before the fix, pixi-task had no self-identification endpoint, so
clients had to know its source repo and version out-of-band. These
tests lock the response shape and transport differentiation.
"""

from __future__ import annotations

from unittest.mock import MagicMock


from pixi_task.lean_mcp_interface import LeanMCPInterface


REQUIRED_FIELDS = {
    "name",
    "version",
    "description",
    "source_url",
    "issues_url",
    "transport",
    "tool_count",
    "registry_size",
    "protocol_version",
}


def _build_interface(transport="stdio", floor=None):
    return LeanMCPInterface(MagicMock(), expose_complexity_floor=floor, transport=transport)


def test_server_info_default_transport_is_stdio():
    info = _build_interface()._server_info_impl()
    assert info["transport"] == "stdio"


def test_server_info_http_transport_label():
    info = _build_interface(transport="http")._server_info_impl()
    assert info["transport"] == "http"


def test_server_info_returns_all_required_fields():
    info = _build_interface()._server_info_impl()
    assert REQUIRED_FIELDS.issubset(info.keys()), (
        f"Missing fields: {REQUIRED_FIELDS - set(info.keys())}"
    )


def test_server_info_name_and_source_url():
    info = _build_interface()._server_info_impl()
    assert info["name"] == "pixi-task"
    assert info["source_url"].startswith("https://github.com/")
    assert info["issues_url"].startswith("https://github.com/")


def test_server_info_tool_count_reflects_floor():
    """tool_count must be the post-floor exposed count, not the registry size."""
    iface_http = _build_interface(floor=["core", "extended"])
    iface_stdio = _build_interface(floor=None)

    info_http = iface_http._server_info_impl()
    info_stdio = iface_stdio._server_info_impl()

    # registry_size is identical (same registry); tool_count differs.
    assert info_http["registry_size"] == info_stdio["registry_size"]
    assert info_http["tool_count"] < info_stdio["tool_count"]
    # And tool_count never exceeds registry_size.
    assert info_http["tool_count"] <= info_http["registry_size"]
    assert info_stdio["tool_count"] == info_stdio["registry_size"]


def test_server_info_reachable_via_dispatch_meta_tool():
    """server_info must be callable through the meta-tool dispatcher."""
    iface = _build_interface(floor=["core", "extended"], transport="http")
    result = iface.dispatch_meta_tool("server_info", {})
    # dispatch_meta_tool returns the _server_info_impl payload directly
    # (no {"tool": ..., "status": ..., "result": ...} wrapper — matches
    # the discover_tools and get_tool_spec branch convention).
    assert "transport" in result
    assert result["transport"] == "http"
    assert "tool_count" in result


def test_server_info_not_gated_by_complexity_floor():
    """server_info is a meta-tool: always reachable, even with restrictive floor."""
    iface = _build_interface(floor=["core"])  # very restrictive floor
    result = iface.dispatch_meta_tool("server_info", {})
    # Should NOT return a 'not exposed' error.
    assert result.get("status") != "error"
    assert "transport" in result


def test_server_info_version_is_a_string():
    info = _build_interface()._server_info_impl()
    assert isinstance(info["version"], str)
    assert len(info["version"]) > 0


def test_http_server_advertises_server_info_in_tools_list():
    """Guard: http_server.py's hand-rolled tools/list MUST include server_info.

    Before the fix to NEXT_TODO Defect 4, the FastMCP @app.tool() decorator
    registered server_info on lean_mcp_interface.py but http_server.py's
    JSON-RPC tools/list response hardcoded only 3 meta-tools, so Claude
    Code's MCP client never saw the new endpoint. This test ensures the
    advertisement list stays in sync with the dispatch surface.
    """
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[1] / "src" / "pixi_task" / "http_server.py"
    ).read_text()

    # Server_info must appear as an advertised tool name in the file.
    # Look for the exact name-string used in the tools/list literal.
    assert '"name": "server_info"' in src, (
        "server_info missing from http_server.py tools/list response; "
        "Claude Code MCP harness will not discover it"
    )
    # And the comment count must agree.
    assert "4 lean meta-tool definitions" in src, (
        "http_server.py comment still mentions 3 meta-tools; update to 4"
    )
