"""Tests for pixi discovery path resolution (issue #17).

Regression coverage ensuring ``check_pixi_available()``, ``get_pixi_path()``
and ``_check_pixi_executable()`` all route through ``_default_pixi_executable()``
instead of a bare ``"pixi"`` PATH lookup, so they don't falsely report pixi as
missing under systemd (where ``shutil.which("pixi")`` returns ``None`` even
when pixi is installed). See https://github.com/Claire-s-Monster/pixi-task/issues/17
"""

import subprocess

from adapters.environment import EnvironmentAdapter
from adapters.project import PixiProjectAdapter


def make_project_adapter() -> PixiProjectAdapter:
    return PixiProjectAdapter(environment=None, logging=None)


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def test_check_pixi_available_honors_override(monkeypatch):
    """PIXI_TASK_PIXI_BIN override must be the binary invoked, not PATH's pixi."""
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", "/custom/pixi")
    monkeypatch.setattr("shutil.which", lambda _c: None)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    adapter = EnvironmentAdapter(working_dir="/tmp")
    assert adapter.check_pixi_available() is True
    assert captured["cmd"][0] == "/custom/pixi"


def test_get_pixi_path_honors_override(monkeypatch):
    """get_pixi_path() must return the override path directly, bypassing which()."""
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", "/custom/pixi")
    monkeypatch.setattr("shutil.which", lambda _c: None)

    adapter = EnvironmentAdapter(working_dir="/tmp")
    assert adapter.get_pixi_path() == "/custom/pixi"


def test_check_pixi_executable_honors_override(monkeypatch):
    """PixiProjectAdapter._check_pixi_executable() must use the override binary."""
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", "/custom/pixi")
    monkeypatch.setattr("shutil.which", lambda _c: None)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    adapter = make_project_adapter()
    assert adapter._check_pixi_executable() is True
    assert captured["cmd"][0] == "/custom/pixi"


def test_check_pixi_available_works_when_which_returns_none(monkeypatch):
    """Systemd reproduction: shutil.which returns None but ~/.pixi/bin/pixi exists."""
    monkeypatch.delenv("PIXI_TASK_PIXI_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda _c: None)
    monkeypatch.setattr("os.path.isfile", lambda p: p.endswith("/.pixi/bin/pixi"))
    monkeypatch.setattr("os.access", lambda _p, _mode: True)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    adapter = EnvironmentAdapter(working_dir="/tmp")
    assert adapter.check_pixi_available() is True
    assert captured["cmd"][0].endswith("/.pixi/bin/pixi")


def test_get_pixi_path_works_when_which_returns_none(monkeypatch):
    """Systemd reproduction for get_pixi_path()."""
    monkeypatch.delenv("PIXI_TASK_PIXI_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda _c: None)
    monkeypatch.setattr("os.path.isfile", lambda p: p.endswith("/.pixi/bin/pixi"))
    monkeypatch.setattr("os.access", lambda _p, _mode: True)

    adapter = EnvironmentAdapter(working_dir="/tmp")
    result = adapter.get_pixi_path()
    assert result is not None
    assert result.endswith("/.pixi/bin/pixi")


def test_check_pixi_executable_works_when_which_returns_none(monkeypatch):
    """Systemd reproduction for PixiProjectAdapter._check_pixi_executable()."""
    monkeypatch.delenv("PIXI_TASK_PIXI_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda _c: None)
    monkeypatch.setattr("os.path.isfile", lambda p: p.endswith("/.pixi/bin/pixi"))
    monkeypatch.setattr("os.access", lambda _p, _mode: True)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    adapter = make_project_adapter()
    assert adapter._check_pixi_executable() is True
    assert captured["cmd"][0].endswith("/.pixi/bin/pixi")


def test_get_pixi_path_returns_none_when_unresolvable(monkeypatch):
    """When nothing resolves pixi, get_pixi_path() must return None (not 'pixi')."""
    monkeypatch.delenv("PIXI_TASK_PIXI_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda _c: None)
    monkeypatch.setattr("os.path.isfile", lambda _p: False)

    adapter = EnvironmentAdapter(working_dir="/tmp")
    assert adapter.get_pixi_path() is None


def test_check_pixi_available_false_on_nonzero_exit(monkeypatch):
    """A non-zero exit code from a resolved binary must report False."""
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", "/custom/pixi")

    def fake_run(cmd, **kwargs):
        return FakeCompletedProcess(returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    adapter = EnvironmentAdapter(working_dir="/tmp")
    assert adapter.check_pixi_available() is False


def test_check_pixi_available_false_on_missing_binary(monkeypatch):
    """A genuinely absent binary (FileNotFoundError/OSError) must also report False."""
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", "/nonexistent/pixi")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(subprocess, "run", fake_run)

    adapter = EnvironmentAdapter(working_dir="/tmp")
    assert adapter.check_pixi_available() is False


def test_check_pixi_executable_false_on_nonzero_exit(monkeypatch):
    """PixiProjectAdapter variant: non-zero exit is False, distinguishable from absence."""
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", "/custom/pixi")

    def fake_run(cmd, **kwargs):
        return FakeCompletedProcess(returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    adapter = make_project_adapter()
    assert adapter._check_pixi_executable() is False


def test_check_pixi_executable_false_on_missing_binary(monkeypatch):
    """PixiProjectAdapter variant: missing binary is False."""
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", "/nonexistent/pixi")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(subprocess, "run", fake_run)

    adapter = make_project_adapter()
    assert adapter._check_pixi_executable() is False
