from __future__ import annotations

from unittest.mock import MagicMock

from core.pixi_service import PixiShellService


def _service():
    executor = MagicMock()
    project = MagicMock()
    logging = MagicMock()
    validation = MagicMock()
    project.is_pixi_project.return_value = True
    executor.run_task_background.return_value = {"status": "running", "job_id": "job1"}
    executor.get_job_status.return_value = {"status": "completed", "exit_code": 0}
    return PixiShellService(
        pixi_executor=executor,
        pixi_project=project,
        logging=logging,
        validation=validation,
        default_working_dir="/tmp/proj",
    )


def test_run_task_background_delegates_with_context():
    service = _service()
    result = service.run_task_background("test", environment="ci")
    assert result["job_id"] == "job1"
    args, kwargs = service.pixi_executor.run_task_background.call_args
    assert args[0] == "test"
    context = args[2]
    assert context.environment == "ci"
    assert kwargs["output_file"] is None


def test_run_task_background_rejects_non_pixi_dir():
    service = _service()
    service.pixi_project.is_pixi_project.return_value = False
    result = service.run_task_background("test")
    assert result["status"] == "error"
    service.pixi_executor.run_task_background.assert_not_called()


def test_get_job_status_delegates():
    service = _service()
    result = service.get_job_status("job1", tail_lines=20)
    assert result["status"] == "completed"
    service.pixi_executor.get_job_status.assert_called_once_with("job1", 20)
