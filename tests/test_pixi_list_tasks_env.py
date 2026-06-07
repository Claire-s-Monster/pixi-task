"""Regression tests for NEXT_TODO Defect 2: pixi_list_tasks missing environment kwarg.

Before the fix, _pixi_list_tasks_impl rejected `environment=` and
get_available_tasks ignored [feature.*.tasks]. This file covers both
the adapter (parses feature envs) and the MCP impl (accepts the kwarg).
"""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock

import pytest

from adapters.project import PixiProjectAdapter
from core.pixi_service import PixiShellService


@pytest.fixture
def feature_env_project(tmp_path):
    """Build a temp pixi project with [tasks] + [feature.*.tasks] + [environments]."""
    pixi_toml = textwrap.dedent(
        """
        [project]
        name = "fixture"
        version = "0.1.0"
        channels = ["conda-forge"]
        platforms = ["linux-64"]

        [tasks]
        build = "echo build"

        [feature.ci.tasks]
        test = "pytest tests/"
        lint = "ruff check"

        [feature.docs.tasks]
        docs = "mkdocs build"

        [environments]
        ci = { features = ["ci"], solve-group = "default" }
        docs = { features = ["docs"] }
        """
    ).strip()
    (tmp_path / "pixi.toml").write_text(pixi_toml)
    return tmp_path


@pytest.fixture
def adapter():
    return PixiProjectAdapter(environment=MagicMock(), logging=MagicMock())


# --- Layer 1: get_available_tasks ---


def test_env_none_unions_base_and_all_features(adapter, feature_env_project):
    tasks = adapter.get_available_tasks(str(feature_env_project))
    assert set(tasks) == {"build", "test", "lint", "docs"}


def test_env_default_returns_base_only(adapter, feature_env_project):
    tasks = adapter.get_available_tasks(str(feature_env_project), environment="default")
    assert tasks == {"build": "echo build"}


def test_env_ci_returns_base_plus_ci_feature_tasks(adapter, feature_env_project):
    tasks = adapter.get_available_tasks(str(feature_env_project), environment="ci")
    assert set(tasks) == {"build", "test", "lint"}
    assert "docs" not in tasks


def test_env_unknown_returns_empty(adapter, feature_env_project):
    tasks = adapter.get_available_tasks(str(feature_env_project), environment="ghost")
    assert tasks == {}


# --- Layer 2/3: pixi_service plumbing ---


@pytest.fixture
def service():
    project = MagicMock()
    project.is_pixi_project.return_value = True
    project.get_available_tasks.return_value = {"test": "pytest"}
    return PixiShellService(
        pixi_executor=MagicMock(),
        pixi_project=project,
        logging=MagicMock(),
        validation=MagicMock(),
    )


def test_list_tasks_propagates_environment(service):
    result = service.list_tasks(working_dir="/tmp/proj", environment="ci")
    service.pixi_project.get_available_tasks.assert_called_once_with(
        "/tmp/proj", environment="ci"
    )
    assert result["tasks"] == {"test": "pytest"}
    assert result["environment"] == "ci"


def test_task_exists_propagates_environment(service):
    assert service.task_exists("test", working_dir="/tmp/proj", environment="ci") is True
    service.pixi_project.get_available_tasks.assert_called_once_with(
        "/tmp/proj", environment="ci"
    )


# --- Layer 4: MCP impl smoke ---


def test_pixi_list_tasks_impl_accepts_environment_kwarg():
    """The MCP-layer impl must accept environment= without TypeError."""
    from pixi_shell.lean_mcp_interface import LeanMCPInterface

    business = MagicMock()
    business.pixi_service.list_tasks.return_value = {
        "tasks": {"test": "pytest"},
        "environment": "ci",
    }
    interface = LeanMCPInterface(business)

    result = interface._pixi_list_tasks_impl(working_dir="/tmp/proj", environment="ci")

    business.pixi_service.list_tasks.assert_called_once_with(
        "/tmp/proj", environment="ci"
    )
    assert result["environment"] == "ci"
