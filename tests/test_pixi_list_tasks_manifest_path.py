"""Regression tests for issue #26: pixi_list_tasks must accept manifest_path.

pixi_run_task already accepts manifest_path (project dir = its parent). These
tests drive pixi_list_tasks through the real execute_tool dispatch path.
"""

from __future__ import annotations

import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from adapters.project import PixiProjectAdapter
from core.pixi_service import PixiShellService
from pixi_task.lean_mcp_interface import LeanMCPInterface


def _manifest(task: str) -> str:
    return textwrap.dedent(
        f"""
        [project]
        name = "fixture"
        version = "0.1.0"
        channels = ["conda-forge"]
        platforms = ["linux-64"]

        [tasks]
        {task} = "echo {task}"
        """
    ).strip()


@pytest.fixture
def interface() -> LeanMCPInterface:
    service = PixiShellService(
        pixi_executor=MagicMock(),
        pixi_project=PixiProjectAdapter(environment=MagicMock(), logging=MagicMock()),
        logging=MagicMock(),
        validation=MagicMock(),
    )
    return LeanMCPInterface(SimpleNamespace(pixi_service=service))


@pytest.fixture
def parent_and_sub(tmp_path):
    parent = tmp_path / "parent"
    sub = parent / "sub"
    sub.mkdir(parents=True)
    (parent / "pixi.toml").write_text(_manifest("parent_task"))
    (sub / "pixi.toml").write_text(_manifest("sub_task"))
    return parent, sub


def _list(interface: LeanMCPInterface, params: dict) -> dict:
    return interface.dispatch_meta_tool(
        "execute_tool", {"tool_name": "pixi_list_tasks", "parameters": params}
    )


def test_manifest_path_lists_parent_tasks(interface, parent_and_sub):
    parent, sub = parent_and_sub
    response = _list(
        interface, {"working_dir": str(sub), "manifest_path": str(parent / "pixi.toml")}
    )
    assert response["status"] == "success", response
    result = response["result"]
    assert "error" not in result
    assert set(result["tasks"]) == {"parent_task"}


def test_manifest_path_with_subdir_lacking_manifest(interface, tmp_path):
    parent = tmp_path / "parent"
    sub = parent / "sub"
    sub.mkdir(parents=True)
    (parent / "pixi.toml").write_text(_manifest("parent_task"))
    response = _list(
        interface, {"working_dir": str(sub), "manifest_path": str(parent / "pixi.toml")}
    )
    assert response["status"] == "success", response
    assert set(response["result"]["tasks"]) == {"parent_task"}


def test_without_manifest_path_lists_working_dir_tasks(interface, parent_and_sub):
    _, sub = parent_and_sub
    response = _list(interface, {"working_dir": str(sub)})
    assert response["status"] == "success", response
    assert set(response["result"]["tasks"]) == {"sub_task"}


def test_missing_manifest_path_returns_error_result(interface, tmp_path):
    missing = tmp_path / "nowhere" / "pixi.toml"
    response = _list(interface, {"working_dir": str(tmp_path), "manifest_path": str(missing)})
    assert response["status"] == "success", response
    result = response["result"]
    assert result["tasks"] == {}
    assert "not a pixi project" in result["error"]


def test_schema_includes_manifest_path(interface):
    schema = interface.tool_registry["pixi_list_tasks"]["schema"]
    run_schema = interface.tool_registry["pixi_run_task"]["schema"]
    assert "manifest_path" in schema["properties"]
    assert (
        schema["properties"]["manifest_path"]["description"]
        == run_schema["properties"]["manifest_path"]["description"]
    )
