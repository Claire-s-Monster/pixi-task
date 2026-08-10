"""Regression tests for GitHub issue #11: execute_tool error envelope.

Before the fix, `_wrap_tool` caught every exception raised by a tool
implementation and returned it as a normal `{"error": ..., "tool": ...}`
dict instead of re-raising. Because `dispatch_meta_tool`'s execute_tool
branch stamps ANY value returned by the wrapped implementation as
`status: "success"`, tool-body failures (e.g. a TypeError from a wrong
kwarg) were silently reported as successful calls.

These tests lock in the corrected contract:
- Tool-body exceptions MUST surface as top-level `status: "error"`.
- Tools that RUN successfully and report failure as *data* (e.g.
  `pixi_run_task` returning `{"success": false, "exit_code": 1, ...}`)
  MUST remain top-level `status: "success"` -- this is correct by design
  and must never be "fixed" via payload sniffing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from pixi_task.lean_mcp_interface import LeanMCPInterface


def _build_interface():
    business = MagicMock()
    return LeanMCPInterface(business, expose_complexity_floor=None)


def test_wrong_kwarg_surfaces_as_top_level_error():
    """Repro: pixi_install called with a wrong kwarg must not report success."""
    iface = _build_interface()
    result = iface.dispatch_meta_tool(
        "execute_tool",
        {"tool_name": "pixi_install", "parameters": {"project_path": "/tmp"}},
    )
    assert result["status"] == "error"
    assert result["status"] != "success"
    assert "project_path" in result["error"]
    assert "unexpected keyword argument" in result["error"]


def test_generic_tool_exception_surfaces_as_top_level_error():
    """Any tool implementation raising must surface as top-level error."""
    iface = _build_interface()

    def _boom(**kwargs):
        raise RuntimeError("boom")

    iface.tool_registry["pixi_install"]["implementation"] = iface._wrap_tool(_boom)

    result = iface.dispatch_meta_tool(
        "execute_tool",
        {"tool_name": "pixi_install", "parameters": {}},
    )
    assert result["status"] == "error"
    assert "boom" in result["error"]


def test_tool_reported_failure_as_data_stays_top_level_success():
    """REGRESSION GUARD: a tool that runs and reports failure as data must
    still be top-level success. Do NOT "fix" this via payload sniffing.
    """
    iface = _build_interface()

    def _ran_but_failed(**kwargs):
        return {"success": False, "exit_code": 1, "stdout": "task failed"}

    iface.tool_registry["pixi_run_task"]["implementation"] = iface._wrap_tool(_ran_but_failed)

    result = iface.dispatch_meta_tool(
        "execute_tool",
        {"tool_name": "pixi_run_task", "parameters": {}},
    )
    assert result["status"] == "success"
    assert result["result"] == {
        "success": False,
        "exit_code": 1,
        "stdout": "task failed",
    }


def test_unknown_tool_name_still_errors():
    """Confirm the existing unknown-tool error path still works."""
    iface = _build_interface()
    result = iface.dispatch_meta_tool(
        "execute_tool",
        {"tool_name": "does_not_exist", "parameters": {}},
    )
    assert result["status"] == "error"
    assert "not found" in result["error"].lower()
