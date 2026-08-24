"""Regression tests for issue #20: PixiHealthCheck.create_unhealthy() hardcoded
all five booleans to False, discarding the values check_health() already
computed. This produced a binary all-true-or-all-false report instead of the
actual per-flag measurements.

These tests construct conditions explicitly with tmp_path and monkeypatch so
they do not depend on ambient environment state (no real pixi install, no
reliance on the repo's own pixi.toml/pixi.lock).
"""

from unittest.mock import MagicMock

from adapters.project import PixiProjectAdapter


def make_project_adapter() -> PixiProjectAdapter:
    return PixiProjectAdapter(environment=MagicMock(), logging=MagicMock())


def test_missing_lock_file_does_not_zero_other_flags(tmp_path, monkeypatch):
    """The issue's named case: valid pixi.toml + resolvable pixi executable +
    missing pixi.lock must report the true/true/false combination, not the
    binary all-False collapse from create_unhealthy()."""
    (tmp_path / "pixi.toml").write_text("[project]\nname = 'demo'\n")

    adapter = make_project_adapter()
    monkeypatch.setattr(adapter, "_check_pixi_executable", lambda: True)
    monkeypatch.setattr(adapter, "_get_environment_path", lambda path: None)

    result = adapter.check_health(str(tmp_path))

    assert result.is_pixi_project is True
    assert result.pixi_executable_found is True
    assert result.lock_file_exists is False
    assert "No pixi.lock file found" in result.issues


def test_no_pixi_toml_reports_not_a_pixi_project(tmp_path):
    """Directory with nothing pixi-related: everything genuinely absent."""
    adapter = make_project_adapter()

    result = adapter.check_health(str(tmp_path))

    assert result.is_pixi_project is False
    assert "No pixi.toml file found" in result.issues


def test_all_healthy_path_reports_all_true_with_no_issues(tmp_path, monkeypatch):
    """When every probe succeeds, all five flags are True and issues is empty."""
    (tmp_path / "pixi.toml").write_text("[project]\nname = 'demo'\n")
    (tmp_path / "pixi.lock").write_text("")
    env_path = tmp_path / ".pixi" / "envs" / "default"
    env_path.mkdir(parents=True)

    adapter = make_project_adapter()
    monkeypatch.setattr(adapter, "_check_pixi_executable", lambda: True)
    monkeypatch.setattr(adapter, "_get_environment_path", lambda path: str(env_path))
    monkeypatch.setattr(adapter, "_check_environment_synced", lambda path: True)

    result = adapter.check_health(str(tmp_path))

    assert result.is_pixi_project is True
    assert result.pixi_executable_found is True
    assert result.lock_file_exists is True
    assert result.environment_exists is True
    assert result.environment_synced is True
    assert result.issues == []
    assert result.is_healthy() is True


def test_exception_path_preserves_flags_measured_before_the_raise(tmp_path, monkeypatch):
    """A failure partway through must still report whatever was already
    measured instead of silently zeroing it via create_unhealthy()."""
    (tmp_path / "pixi.toml").write_text("[project]\nname = 'demo'\n")
    (tmp_path / "pixi.lock").write_text("")

    adapter = make_project_adapter()
    monkeypatch.setattr(adapter, "_check_pixi_executable", lambda: True)

    def raise_on_env_path(path):
        raise RuntimeError("boom")

    monkeypatch.setattr(adapter, "_get_environment_path", raise_on_env_path)

    result = adapter.check_health(str(tmp_path))

    # Measured before the raise: must survive.
    assert result.is_pixi_project is True
    assert result.pixi_executable_found is True
    assert result.lock_file_exists is True
    # Never reached because of the raise: stays at its initialised default.
    assert result.environment_exists is False
    assert result.environment_synced is False
    assert any("Health check error" in issue for issue in result.issues)
