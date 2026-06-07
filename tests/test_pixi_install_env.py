"""Regression tests for NEXT_TODO Defect 3: pixi_install missing environment kwarg.

Before the fix, pixi_install accepted only working_dir, so feature
environments could not be pre-warmed via the MCP. This file covers all
three layers: executor adapter (builds --environment flag), service
(plumbs the kwarg), and MCP impl (accepts it without TypeError).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from adapters.execution import PixiExecutionAdapter
from core.models import PixiExecutionContext
from core.pixi_service import PixiShellService


# --- Layer 1: executor adapter constructs --environment flag ---


def test_executor_install_appends_environment_flag():
    """When context.environment is set, the install command must include --environment <env>."""
    adapter = PixiExecutionAdapter(
        environment=MagicMock(),
        logging=MagicMock(),
        validation=MagicMock(),
    )
    context = PixiExecutionContext(
        working_dir="/tmp/proj",
        timeout=600,
        environment="ci",
    )

    with patch.object(
        adapter,
        "_execute_with_timeout",
        return_value=("ok", "", 0, 0.1),
    ) as mock_exec:
        adapter.install(context)

    call_kwargs = mock_exec.call_args.kwargs
    command = call_kwargs["command"]
    # pixi executable + install + --environment + ci
    assert command[-3:] == ["install", "--environment", "ci"]


def test_executor_install_without_environment_omits_flag():
    """When context.environment is None, --environment must NOT appear in the command."""
    adapter = PixiExecutionAdapter(
        environment=MagicMock(),
        logging=MagicMock(),
        validation=MagicMock(),
    )
    context = PixiExecutionContext(
        working_dir="/tmp/proj",
        timeout=600,
    )

    with patch.object(
        adapter,
        "_execute_with_timeout",
        return_value=("ok", "", 0, 0.1),
    ) as mock_exec:
        adapter.install(context)

    command = mock_exec.call_args.kwargs["command"]
    assert "--environment" not in command


# --- Layer 2: service plumbs environment into context ---


@pytest.fixture
def service():
    project = MagicMock()
    project.is_pixi_project.return_value = True
    executor = MagicMock()
    # Mimic a successful PixiTaskResult shape
    executor.install.return_value = MagicMock(
        success=True, stdout="ok", stderr="", execution_time=0.1
    )
    return PixiShellService(
        pixi_executor=executor,
        pixi_project=project,
        logging=MagicMock(),
        validation=MagicMock(),
    )


def test_service_install_passes_environment_to_executor(service):
    result = service.install(working_dir="/tmp/proj", environment="ci")

    service.pixi_executor.install.assert_called_once()
    ctx = service.pixi_executor.install.call_args.args[0]
    assert isinstance(ctx, PixiExecutionContext)
    assert ctx.environment == "ci"
    assert ctx.working_dir == "/tmp/proj"

    assert result["success"] is True
    assert result["environment"] == "ci"


def test_service_install_not_a_pixi_project_still_reports_env(service):
    service.pixi_project.is_pixi_project.return_value = False
    result = service.install(working_dir="/not/a/project", environment="ci")
    assert result["success"] is False
    assert result["environment"] == "ci"
    service.pixi_executor.install.assert_not_called()


# --- Layer 3: MCP impl accepts environment kwarg ---


def test_pixi_install_impl_accepts_environment_kwarg():
    """The MCP-layer impl must accept environment= without TypeError."""
    from pixi_shell.lean_mcp_interface import LeanMCPInterface

    business = MagicMock()
    business.pixi_service.install.return_value = {
        "success": True,
        "stdout": "ok",
        "stderr": "",
        "execution_time": 0.1,
        "environment": "ci",
    }
    interface = LeanMCPInterface(business)

    result = interface._pixi_install_impl(working_dir="/tmp/proj", environment="ci")

    business.pixi_service.install.assert_called_once_with(
        "/tmp/proj", environment="ci"
    )
    assert result["environment"] == "ci"
