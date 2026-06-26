"""Tests for working_dir resolution in PixiShellService.

Regression coverage for the fix that removed the startup os.chdir and made the
service resolve relative/omitted working_dir against a configured base instead
of the server's own process directory.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock

from core.pixi_service import PixiShellService


def make_service(default_working_dir=None):
    return PixiShellService(
        pixi_executor=MagicMock(),
        pixi_project=MagicMock(),
        logging=MagicMock(),
        validation=MagicMock(),
        default_working_dir=default_working_dir,
    )


def test_resolve_none_uses_cwd_when_no_base():
    service = make_service(default_working_dir=None)
    assert service._resolve_working_dir(None) == os.getcwd()


def test_resolve_absolute_path_unchanged():
    service = make_service(default_working_dir="/base")
    assert service._resolve_working_dir("/abs/project") == "/abs/project"


def test_resolve_relative_against_cwd_when_no_base():
    service = make_service(default_working_dir=None)
    assert service._resolve_working_dir("sub") == str(Path(os.getcwd()) / "sub")


def test_resolve_none_uses_configured_base():
    service = make_service(default_working_dir="/base")
    assert service._resolve_working_dir(None) == "/base"


def test_resolve_relative_against_configured_base():
    service = make_service(default_working_dir="/base")
    assert service._resolve_working_dir("sub") == str(Path("/base") / "sub")


def test_resolve_does_not_change_process_cwd():
    service = make_service(default_working_dir="/base")
    before = os.getcwd()
    service._resolve_working_dir("relative/path")
    assert os.getcwd() == before


def test_run_task_resolves_relative_working_dir_against_base():
    service = make_service(default_working_dir="/base")
    service.pixi_project.is_pixi_project.return_value = True
    service.run_task(task_name="test", working_dir="sub")
    # PixiExecutorPort.run_task(task_name, args, context) -> context is 3rd positional
    ctx = service.pixi_executor.run_task.call_args.args[2]
    assert ctx.working_dir == str(Path("/base") / "sub")
