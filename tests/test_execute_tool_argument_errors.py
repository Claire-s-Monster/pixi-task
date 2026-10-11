"""Regression tests for issue #32: argument-binding failures in execute_tool.

pixi_run_task must accept `task` as an alias for `task_name`, and a call whose
arguments cannot be bound to the tool signature must return an error result
naming the schema's params. Tests drive the real execute_tool dispatch path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pixi_task.lean_mcp_interface import LeanMCPInterface


@pytest.fixture
def interface() -> LeanMCPInterface:
    service = MagicMock()
    service.run_task.return_value = {"success": True}
    service.get_job_status.side_effect = lambda job_id, tail_lines: {"job": job_id}
    return LeanMCPInterface(SimpleNamespace(pixi_service=service))


def _exec(interface: LeanMCPInterface, tool: str, params: dict) -> dict:
    return interface.dispatch_meta_tool("execute_tool", {"tool_name": tool, "parameters": params})


def test_task_alias_runs_task(interface):
    response = _exec(interface, "pixi_run_task", {"task": "test"})
    assert response["status"] == "success", response
    assert interface.business_engine.pixi_service.run_task.call_args.args[0] == "test"


def test_task_alias_equal_to_task_name_is_accepted(interface):
    response = _exec(interface, "pixi_run_task", {"task": "test", "task_name": "test"})
    assert response["status"] == "success", response


def test_task_alias_conflicting_with_task_name_is_error(interface):
    response = _exec(interface, "pixi_run_task", {"task": "lint", "task_name": "test"})
    assert response["status"] == "error"
    assert "task" in response["error"] and "task_name" in response["error"]
    interface.business_engine.pixi_service.run_task.assert_not_called()


def test_neither_task_nor_task_name_is_error_naming_task_name(interface):
    response = _exec(interface, "pixi_run_task", {"working_dir": "/x"})
    assert response["status"] == "error"
    assert "task_name" in response["error"]
    assert "task_name" in response["required"]


def test_schema_keeps_task_name_required_and_mentions_alias(interface):
    schema = interface.tool_registry["pixi_run_task"]["schema"]
    assert schema["required"] == ["task_name"]
    assert "task" not in schema["properties"]
    assert "task" in schema["properties"]["task_name"]["description"]


def test_missing_argument_error_lists_schema_params(interface):
    response = _exec(interface, "pixi_task_status", {})
    assert response["status"] == "error"
    assert response["tool"] == "pixi_task_status"
    assert "job_id" in response["error"]
    assert "job_id" in response["required"]
    assert {"job_id", "tail_lines"} <= set(response["properties"])


def test_unexpected_argument_error_names_offender_and_schema(interface):
    response = _exec(interface, "pixi_task_status", {"job_id": "j1", "bogus": 1})
    assert response["status"] == "error"
    assert "bogus" in response["error"]
    assert "job_id" in response["required"]
    assert "tail_lines" in response["properties"]


def test_typeerror_inside_tool_logic_is_not_reported_as_binding_error(interface):
    interface.business_engine.pixi_service.get_job_status.side_effect = TypeError("boom")
    response = _exec(interface, "pixi_task_status", {"job_id": "j1"})
    assert response["status"] == "error"
    assert response["error"] == "boom"
    assert "properties" not in response
