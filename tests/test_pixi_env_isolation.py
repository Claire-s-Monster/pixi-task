"""Tests for pixi environment variable isolation (issue #6).

Regression coverage ensuring that pixi activation variables inherited from the
MCP server's own parent environment are stripped from the child process
environment, so ``pixi run`` activates the *target* project rather than the
server's project.
"""

import os

from core.models import CONFLICTING_PIXI_ENV_VARS, PixiExecutionContext


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
