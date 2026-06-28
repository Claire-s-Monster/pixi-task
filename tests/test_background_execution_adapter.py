from __future__ import annotations

from unittest.mock import MagicMock

from adapters.execution import PixiExecutionAdapter
from core.models import PixiExecutionContext


def _adapter_with_mock_jobs():
    validation = MagicMock()
    validation.validate_task_name.return_value = True
    validation.validate_arguments.side_effect = lambda a: a
    adapter = PixiExecutionAdapter(
        environment=MagicMock(),
        logging=MagicMock(),
        validation=validation,
    )
    adapter.jobs = MagicMock()
    adapter.jobs.launch.return_value = {"status": "running", "job_id": "abc"}
    return adapter


def test_run_task_background_builds_command_and_delegates():
    adapter = _adapter_with_mock_jobs()
    context = PixiExecutionContext(working_dir="/tmp/proj", environment="ci")
    result = adapter.run_task_background("test", ["-k", "foo"], context)
    assert result["job_id"] == "abc"
    kwargs = adapter.jobs.launch.call_args.kwargs
    command = kwargs["command"]
    assert command[:2] == [context.pixi_executable, "run"]
    assert "--environment" in command and "ci" in command
    assert command[-3:] == ["test", "-k", "foo"]


def test_run_task_background_rejects_invalid_task_name():
    adapter = _adapter_with_mock_jobs()
    adapter.validation.validate_task_name.return_value = False
    context = PixiExecutionContext(working_dir="/tmp/proj")
    result = adapter.run_task_background("bad;name", [], context)
    assert result["status"] == "error"
    adapter.jobs.launch.assert_not_called()


def test_get_job_status_delegates_to_manager():
    adapter = _adapter_with_mock_jobs()
    adapter.jobs.status.return_value = {"status": "completed", "exit_code": 0}
    result = adapter.get_job_status("abc", tail_lines=10)
    assert result["status"] == "completed"
    adapter.jobs.status.assert_called_once_with("abc", 10)
