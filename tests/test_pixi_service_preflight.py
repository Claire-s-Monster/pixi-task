"""Regression test for NEXT_TODO Defect 1: pre-flight task check ignored -e env.

Before the fix, run_task() called get_available_tasks(project_dir) and returned
"Task '<name>' not found" if the task lived under [feature.<env>.tasks] instead
of the top-level [tasks] table — even when environment="<env>" was passed.

This test mocks the dependencies and asserts that run_task no longer
short-circuits on a feature-env task; the call must reach the executor.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.models import PixiTaskResult
from core.pixi_service import PixiShellService


@pytest.fixture
def service():
    """Build a PixiShellService with all ports mocked."""
    executor = MagicMock()
    project = MagicMock()
    logging = MagicMock()
    validation = MagicMock()

    # Project is recognised, but its top-level [tasks] table is empty —
    # simulating a feature-env-only task definition.
    project.is_pixi_project.return_value = True
    project.get_available_tasks.return_value = {}

    # Executor returns a successful result so we can confirm we reached it.
    executor.run_task.return_value = PixiTaskResult(
        success=True,
        stdout="ok",
        stderr="",
        exit_code=0,
        execution_time=0.01,
        task_name="test",
        working_dir="/tmp/proj",
        command_line="pixi run -e ci test",
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:00+00:00",
    )

    return PixiShellService(
        pixi_executor=executor,
        pixi_project=project,
        logging=logging,
        validation=validation,
    )


def test_run_task_feature_env_reaches_executor(service):
    """run_task must NOT short-circuit when a task is defined under a feature env."""
    result = service.run_task(
        task_name="test",
        args=[],
        working_dir="/tmp/proj",
        environment="ci",
    )

    # The pre-flight check is gone, so the executor must have been called
    # exactly once with the requested task + environment.
    service.pixi_executor.run_task.assert_called_once()
    call_args = service.pixi_executor.run_task.call_args
    assert call_args.args[0] == "test"

    context = call_args.args[2]
    assert context.environment == "ci"

    # And we must NOT see the old "Task '...' not found" error message.
    assert "not found" not in result["stderr"]
    assert result["success"] is True


def test_run_task_still_rejects_non_pixi_dir(service):
    """is_pixi_project guard must still fire when there is no pixi.toml."""
    service.pixi_project.is_pixi_project.return_value = False

    result = service.run_task(task_name="whatever", working_dir="/not/a/project")

    service.pixi_executor.run_task.assert_not_called()
    assert result["success"] is False
    assert "not a pixi project" in result["stderr"]
