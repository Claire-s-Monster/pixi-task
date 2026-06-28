from __future__ import annotations

from unittest.mock import MagicMock

from pixi_task.lean_mcp_interface import LeanMCPInterface


def _interface(floor=None):
    return LeanMCPInterface(MagicMock(), expose_complexity_floor=floor)


def test_pixi_run_task_schema_has_background_params():
    iface = _interface()
    spec = iface.dispatch_meta_tool("get_tool_spec", {"tool_name": "pixi_run_task"})
    props = spec["schema"]["properties"]
    assert "background" in props
    assert props["background"]["default"] is False
    assert "output_file" in props


def test_pixi_task_status_tool_registered_as_core():
    iface = _interface()
    assert "pixi_task_status" in iface.tool_registry
    assert iface.tool_registry["pixi_task_status"]["complexity"] == "core"


def test_background_true_routes_to_run_task_background():
    engine = MagicMock()
    engine.pixi_service.run_task_background.return_value = {"status": "running", "job_id": "j"}
    iface = LeanMCPInterface(engine)
    result = iface._pixi_run_task_impl("test", background=True, environment="ci")
    assert result["job_id"] == "j"
    engine.pixi_service.run_task_background.assert_called_once()
    engine.pixi_service.run_task.assert_not_called()


def test_background_false_routes_to_run_task():
    engine = MagicMock()
    engine.pixi_service.run_task.return_value = {"success": True}
    iface = LeanMCPInterface(engine)
    iface._pixi_run_task_impl("test", background=False)
    engine.pixi_service.run_task.assert_called_once()
    engine.pixi_service.run_task_background.assert_not_called()


def test_pixi_task_status_impl_delegates():
    engine = MagicMock()
    engine.pixi_service.get_job_status.return_value = {"status": "completed"}
    iface = LeanMCPInterface(engine)
    result = iface._pixi_task_status_impl("job1", tail_lines=5)
    assert result["status"] == "completed"
    engine.pixi_service.get_job_status.assert_called_once_with("job1", 5)


def test_http_floor_exposes_pixi_task_status():
    iface = _interface(["core", "extended"])
    result = iface.dispatch_meta_tool("discover_tools", {})
    names = {t["name"] for t in result["available_tools"]}
    assert "pixi_task_status" in names
