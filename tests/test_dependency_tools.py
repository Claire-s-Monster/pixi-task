"""Tests for issue #60: pixi_add_dependency / pixi_remove_dependency over HTTP.

Covers exposure under the HTTP complexity floor, the ``packages`` array
schema, command construction (feature / platform / channel), the absence of
any PyPI support, compact output, and hidden-tool reporting.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

import adapters.project as project_module
from adapters.project import PixiProjectAdapter
from pixi_task.lean_mcp_interface import LeanMCPInterface

HTTP_FLOOR = ["core", "extended"]


def _iface(floor=HTTP_FLOOR) -> LeanMCPInterface:
    return LeanMCPInterface(MagicMock(), expose_complexity_floor=floor)


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "pixi.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / "pixi.lock").write_text("lock-v1")
    monkeypatch.setattr(project_module, "_default_pixi_executable", lambda: "pixi")
    return tmp_path


def _adapter() -> PixiProjectAdapter:
    return PixiProjectAdapter(environment=None, logging=MagicMock())


def _fake_run(captured, returncode=0, stdout="", stderr="", mutate=None):
    def run(cmd, **kwargs):
        captured["cmd"] = cmd
        if mutate:
            mutate()
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    return run


# --- exposure -------------------------------------------------------------


def test_both_tools_exposed_under_http_floor():
    result = _iface().dispatch_meta_tool("discover_tools", {})
    names = {t["name"] for t in result["available_tools"]}
    assert {"pixi_add_dependency", "pixi_remove_dependency"} <= names


def test_pixi_init_still_hidden_under_http_floor():
    result = _iface().dispatch_meta_tool("discover_tools", {})
    names = {t["name"] for t in result["available_tools"]}
    assert "pixi_init" not in names
    assert "pixi_init" in result["hidden_tools"]


def test_hidden_tools_reported_and_consistent():
    iface = _iface()
    result = iface.dispatch_meta_tool("discover_tools", {})
    hidden = result["hidden_tools"]
    assert len(hidden) + result["total_tools"] == len(iface.tool_registry)
    info = iface.dispatch_meta_tool("server_info", {})
    assert info["hidden_tools"] == hidden
    assert info["registry_size"] - info["tool_count"] == len(hidden)


def test_no_hidden_tools_without_floor():
    assert _iface(None).dispatch_meta_tool("discover_tools", {})["hidden_tools"] == []


# --- schema ---------------------------------------------------------------


@pytest.mark.parametrize("tool", ["pixi_add_dependency", "pixi_remove_dependency"])
def test_schema_has_packages_array_and_no_package_or_pypi(tool):
    spec = _iface().dispatch_meta_tool("get_tool_spec", {"tool_name": tool})
    props = spec["schema"]["properties"]
    assert props["packages"]["type"] == "array"
    assert props["packages"]["items"]["type"] == "string"
    assert props["packages"]["minItems"] == 1
    assert spec["schema"]["required"] == ["packages"]
    assert "package" not in props
    assert "is_dev" not in props
    assert not any("pypi" in key.lower() for key in props)
    assert "feature" in props and "platform" in props
    assert props["platform"]["type"] == "array"
    assert "package" not in str(spec["examples"]).replace("packages", "")


def test_add_schema_keeps_channel():
    spec = _iface().dispatch_meta_tool("get_tool_spec", {"tool_name": "pixi_add_dependency"})
    assert "channel" in spec["schema"]["properties"]


# --- command construction -------------------------------------------------


def test_add_multiple_packages(project, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(project_module.subprocess, "run", _fake_run(captured))
    _adapter().add_dependency(["xlrd", "openpyxl>=3.1"], working_dir=str(project))
    assert captured["cmd"] == ["pixi", "add", "xlrd", "openpyxl>=3.1"]


def test_add_feature_and_platforms(project, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(project_module.subprocess, "run", _fake_run(captured))
    _adapter().add_dependency(
        ["xlrd"],
        feature="quality",
        platform=["linux-64", "osx-arm64"],
        working_dir=str(project),
    )
    cmd = captured["cmd"]
    assert cmd[:2] == ["pixi", "add"]
    assert cmd[cmd.index("--feature") + 1] == "quality"
    platforms = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--platform"]
    assert platforms == ["linux-64", "osx-arm64"]
    assert cmd[-1] == "xlrd"


def test_add_channel_prefixes_specs(project, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(project_module.subprocess, "run", _fake_run(captured))
    _adapter().add_dependency(["a", "other::b"], channel="conda-forge", working_dir=str(project))
    assert captured["cmd"][-2:] == ["conda-forge::a", "other::b"]


def test_remove_feature_and_platform(project, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(project_module.subprocess, "run", _fake_run(captured))
    _adapter().remove_dependency(
        ["xlrd", "pytest"], feature="dev", platform=["linux-64"], working_dir=str(project)
    )
    assert captured["cmd"] == [
        "pixi",
        "remove",
        "--feature",
        "dev",
        "--platform",
        "linux-64",
        "xlrd",
        "pytest",
    ]


def test_pypi_flag_never_built(project, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(project_module.subprocess, "run", _fake_run(captured))
    adapter = _adapter()
    adapter.add_dependency(
        ["x"], feature="f", platform=["linux-64"], channel="c", working_dir=str(project)
    )
    assert "--pypi" not in captured["cmd"]
    adapter.remove_dependency(["x"], feature="f", platform=["linux-64"], working_dir=str(project))
    assert "--pypi" not in captured["cmd"]


@pytest.mark.parametrize("bad", [[], ["--pypi"], [""], "xlrd"])
def test_invalid_packages_rejected_without_running(project, monkeypatch, bad):
    called: list[int] = []
    monkeypatch.setattr(project_module.subprocess, "run", lambda *a, **k: called.append(1))
    result = _adapter().add_dependency(bad, working_dir=str(project))
    assert result.success is False
    assert called == []


# --- compact output -------------------------------------------------------


def test_add_output_is_compact_and_reports_changes(project, monkeypatch):
    captured: dict = {}
    noisy = "solving...\n" * 500
    stderr = noisy + "\x1b[32m✔\x1b[0m Added xlrd >=2.0.1,<3\n✔ Added openpyxl >=3.1\n"

    def mutate():
        (project / "pixi.toml").write_text('[project]\nname = "demo"\n[dependencies]\nxlrd = "*"\n')
        (project / "pixi.lock").write_text("lock-v2")

    monkeypatch.setattr(
        project_module.subprocess, "run", _fake_run(captured, stderr=stderr, mutate=mutate)
    )
    result = _adapter().add_dependency(["xlrd", "openpyxl>=3.1"], working_dir=str(project))
    assert result.success is True
    data = result.data
    assert data["packages"] == ["xlrd", "openpyxl>=3.1"]
    assert data["added"] == ["xlrd >=2.0.1,<3", "openpyxl >=3.1"]
    assert data["changed_files"] == ["pixi.toml", "pixi.lock"]
    assert data["exit_code"] == 0
    assert "solving" not in str(data) and "solving" not in result.message
    assert "stderr_tail" not in data


def test_unchanged_files_not_reported(project, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(project_module.subprocess, "run", _fake_run(captured))
    result = _adapter().add_dependency(["xlrd"], working_dir=str(project))
    assert result.data["changed_files"] == []
    assert result.data["added"] == []


def test_remove_output_shape(project, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        project_module.subprocess, "run", _fake_run(captured, stderr="✔ Removed xlrd\n")
    )
    result = _adapter().remove_dependency(["xlrd"], working_dir=str(project))
    assert result.data["removed"] == ["xlrd"]
    assert result.data["packages"] == ["xlrd"]
    assert result.data["exit_code"] == 0


def test_failure_returns_short_stderr_tail(project, monkeypatch):
    captured: dict = {}
    stderr = "\n".join(f"line {i}" for i in range(200))
    monkeypatch.setattr(
        project_module.subprocess, "run", _fake_run(captured, returncode=1, stderr=stderr)
    )
    result = _adapter().add_dependency(["nope"], working_dir=str(project))
    assert result.success is False
    assert result.data["exit_code"] == 1
    tail = result.data["stderr_tail"]
    assert "line 199" in tail and "line 0\n" not in tail
    assert len(tail.splitlines()) <= 10
    assert len(result.message) < 1000
