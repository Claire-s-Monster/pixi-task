"""Tests for pixi environment path resolution (issue #23).

Regression coverage ensuring ``_get_environment_path()`` and the three
subprocess call sites in ``PixiProjectAdapter`` (``add_dependency``,
``remove_dependency``, ``init_project``) no longer depend on a bare
``"pixi"`` PATH lookup. Under the systemd user unit this server runs from,
PATH has no pixi, so a bare ``["pixi", ...]`` invocation raises
``FileNotFoundError``. ``_get_environment_path`` must never shell out at
all -- it is filesystem-only -- and the three command sites must route
through ``_default_pixi_executable()``.
See https://github.com/Claire-s-Monster/pixi-task/issues/23
"""

import subprocess

import adapters.project as project_module
from adapters.project import PixiProjectAdapter


def make_project_adapter() -> PixiProjectAdapter:
    return PixiProjectAdapter(environment=None, logging=None)


def test_get_environment_path_default_env_no_subprocess(tmp_path, monkeypatch):
    """Named issue case: .pixi/envs/default must resolve without shelling out."""
    envs_dir = tmp_path / ".pixi" / "envs" / "default"
    envs_dir.mkdir(parents=True)

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(project_module.subprocess, "run", fake_run)

    adapter = make_project_adapter()
    assert adapter._get_environment_path(str(tmp_path)) == str(envs_dir)


def test_check_health_finds_default_env_when_pixi_unresolvable(tmp_path, monkeypatch):
    """End-to-end: check_health must report the environment as present even
    when subprocess.run would raise FileNotFoundError for any pixi call."""
    (tmp_path / "pixi.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / "pixi.lock").write_text("")
    envs_dir = tmp_path / ".pixi" / "envs" / "default"
    envs_dir.mkdir(parents=True)

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(project_module.subprocess, "run", fake_run)

    adapter = make_project_adapter()
    monkeypatch.setattr(adapter, "_check_pixi_executable", lambda: True)

    health = adapter.check_health(str(tmp_path))
    assert health.environment_exists is True
    assert "Pixi environment not found" not in health.issues


def test_get_environment_path_non_default_env_name(tmp_path):
    """A project may name its environment something other than 'default'."""
    envs_dir = tmp_path / ".pixi" / "envs" / "quality"
    envs_dir.mkdir(parents=True)

    adapter = make_project_adapter()
    assert adapter._get_environment_path(str(tmp_path)) == str(envs_dir)


def test_get_environment_path_returns_none_when_absent(tmp_path):
    """No .pixi directory at all must return None, not raise."""
    adapter = make_project_adapter()
    assert adapter._get_environment_path(str(tmp_path)) is None


def test_add_dependency_uses_default_pixi_executable(tmp_path, monkeypatch):
    """add_dependency must invoke the resolved pixi binary, not a bare 'pixi'."""
    (tmp_path / "pixi.toml").write_text('[project]\nname = "demo"\n')

    monkeypatch.setattr(project_module, "_default_pixi_executable", lambda: "/sentinel/bin/pixi")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(project_module.subprocess, "run", fake_run)

    adapter = make_project_adapter()
    adapter.add_dependency("numpy", working_dir=str(tmp_path))

    assert captured["cmd"][0] == "/sentinel/bin/pixi"


def test_remove_dependency_uses_default_pixi_executable(tmp_path, monkeypatch):
    """remove_dependency must invoke the resolved pixi binary, not a bare 'pixi'."""
    (tmp_path / "pixi.toml").write_text('[project]\nname = "demo"\n')

    monkeypatch.setattr(project_module, "_default_pixi_executable", lambda: "/sentinel/bin/pixi")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(project_module.subprocess, "run", fake_run)

    adapter = make_project_adapter()
    adapter.remove_dependency("numpy", working_dir=str(tmp_path))

    assert captured["cmd"][0] == "/sentinel/bin/pixi"


def test_init_project_uses_default_pixi_executable(tmp_path, monkeypatch):
    """init_project must invoke the resolved pixi binary, not a bare 'pixi'."""
    monkeypatch.setattr(project_module, "_default_pixi_executable", lambda: "/sentinel/bin/pixi")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(project_module.subprocess, "run", fake_run)

    adapter = make_project_adapter()
    adapter.init_project(str(tmp_path))

    assert captured["cmd"][0] == "/sentinel/bin/pixi"
