"""Tests for pixi environment variable isolation (issue #6).

Regression coverage ensuring that pixi activation variables inherited from the
MCP server's own parent environment are stripped from the child process
environment, so ``pixi run`` activates the *target* project rather than the
server's project.
"""

import os

from core.models import (
    CONFLICTING_PIXI_ENV_VARS,
    PixiExecutionContext,
    _default_pixi_executable,
)


def make_context(**kwargs) -> PixiExecutionContext:
    return PixiExecutionContext(working_dir="/tmp", **kwargs)


def test_conflicting_vars_stripped_from_full_env(monkeypatch):
    """get_full_env() must not contain any CONFLICTING_PIXI_ENV_VARS."""
    for var in CONFLICTING_PIXI_ENV_VARS:
        monkeypatch.setenv(var, "injected-value")

    env = make_context().get_full_env()

    for var in CONFLICTING_PIXI_ENV_VARS:
        assert var not in env, f"{var} must be stripped but was present"


def test_explicit_environment_vars_still_present(monkeypatch):
    """Caller-supplied environment_vars must survive even when conflicting vars are stripped."""
    monkeypatch.setenv("PIXI_PROJECT_MANIFEST", "/server/pixi.toml")

    env = make_context(environment_vars={"MY_CUSTOM_VAR": "hello"}).get_full_env()

    assert env.get("MY_CUSTOM_VAR") == "hello"
    assert "PIXI_PROJECT_MANIFEST" not in env


def test_non_pixi_vars_preserved(monkeypatch):
    """Unrelated environment variables must not be stripped."""
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
    monkeypatch.setenv("HOME", os.environ.get("HOME", "/root"))

    env = make_context().get_full_env()

    assert "PATH" in env
    assert "HOME" in env


def test_environment_vars_override_os_environ(monkeypatch):
    """environment_vars values must take precedence over inherited os.environ values."""
    monkeypatch.setenv("MY_VAR", "original")

    env = make_context(environment_vars={"MY_VAR": "overridden"}).get_full_env()

    assert env["MY_VAR"] == "overridden"


def test_pixi_dir_prepended_to_path(monkeypatch):
    """dirname(pixi_executable) must be on PATH even when os.environ lacks it (issue #14)."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = make_context(pixi_executable="/opt/tools/bin/pixi").get_full_env()

    assert env["PATH"].split(os.pathsep)[0] == "/opt/tools/bin"
    assert "/usr/bin" in env["PATH"].split(os.pathsep)


def test_pixi_dir_not_duplicated_on_path(monkeypatch):
    """An already-present pixi directory must not be added twice."""
    monkeypatch.setenv("PATH", f"/opt/tools/bin{os.pathsep}/usr/bin")

    env = make_context(pixi_executable="/opt/tools/bin/pixi").get_full_env()

    assert env["PATH"].split(os.pathsep).count("/opt/tools/bin") == 1


def test_bare_pixi_executable_leaves_path_untouched(monkeypatch):
    """A bare command name has no directory, so PATH must be unchanged."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = make_context(pixi_executable="pixi").get_full_env()

    assert env["PATH"] == "/usr/bin:/bin"


def test_explicit_env_override_wins_for_default_executable(monkeypatch):
    """PIXI_TASK_PIXI_BIN takes precedence over every other resolution step."""
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", "/custom/pixi")

    assert _default_pixi_executable() == "/custom/pixi"


def test_default_executable_falls_back_to_bare_name(monkeypatch):
    """With no override, no ~/.pixi copy and nothing on PATH, fall back to 'pixi'."""
    monkeypatch.delenv("PIXI_TASK_PIXI_BIN", raising=False)
    monkeypatch.setattr("os.path.isfile", lambda _p: False)
    monkeypatch.setattr("shutil.which", lambda _c: None)

    assert _default_pixi_executable() == "pixi"
