"""Live rattler-build tests (#45) using the real pixi; no fake binary."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from adapters.background import BackgroundJobManager
from adapters.execution import PixiExecutionAdapter
from core.pixi_service import PixiShellService
from pixi_task.lean_mcp_interface import LeanMCPInterface

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("pixi") is None, reason="pixi not installed"),
]

OK_SCRIPT = '["mkdir -p $PREFIX/share", "echo ok > $PREFIX/share/probe.txt"]'

RECIPES = {
    "solve": """\
package: {name: probe-solve, version: 0.1.0}
build: {noarch: generic, script: ["echo hi"]}
requirements: {host: [definitely-not-a-real-package-xyz]}
""",
    "ok": f"""\
package: {{name: probe-ok, version: 0.1.0}}
build: {{noarch: generic, script: {OK_SCRIPT}}}
tests: [{{script: ["test -f $PREFIX/share/probe.txt"]}}]
""",
    "needsconda": """\
package: {name: probe-needsconda, version: 0.1.0}
build:
  noarch: generic
  script: ["conda --version", "mkdir -p $PREFIX/share", "echo ok > $PREFIX/share/probe.txt"]
""",
    "buildfail": """\
package: {name: probe-buildfail, version: 0.1.0}
build: {noarch: generic, script: ["echo BUILD-ERROR-MARKER", "exit 3"]}
tests: [{script: ["test -f $PREFIX/share/probe.txt"]}]
""",
}


@pytest.fixture
def live(tmp_path):
    for name, text in RECIPES.items():
        (tmp_path / name).mkdir()
        (tmp_path / name / "recipe.yaml").write_text(text)
    adapter = PixiExecutionAdapter(
        MagicMock(), MagicMock(), MagicMock(), BackgroundJobManager(str(tmp_path / "jobs"))
    )
    service = PixiShellService(
        pixi_executor=adapter,
        pixi_project=MagicMock(),
        logging=MagicMock(),
        validation=MagicMock(),
        default_working_dir=str(tmp_path),
    )
    iface = LeanMCPInterface(MagicMock(pixi_service=service))

    def call(tool, params):
        return iface.dispatch_meta_tool("execute_tool", {"tool_name": tool, "parameters": params})

    return SimpleNamespace(tmp=tmp_path, call=call)


def _build_params(live, recipe, **extra):
    return {
        "recipe": recipe,
        "channels": ["conda-forge"],
        "output_dir": str(live.tmp / "out"),
        "working_dir": str(live.tmp),
        **extra,
    }


def _background_result(live, recipe, **extra):
    launched = live.call(
        "rattler_build_build", _build_params(live, recipe, background=True, **extra)
    )
    assert launched["status"] == "success", launched
    job_id = launched["result"]["job_id"]
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        waited = live.call("pixi_wait", {"job_id": job_id, "wait_s": 15})
        assert waited["status"] == "success", waited
        if waited["result"]["state"] == "done":
            break
    else:
        pytest.fail(f"job {job_id} did not finish within 600s")
    resp = live.call("rattler_build_result", {"job_id": job_id})
    assert resp["status"] == "success", resp
    return resp["result"]


@pytest.mark.timeout(900)
def test_live_solve_failure(live):
    resp = live.call(
        "rattler_build_build",
        _build_params(live, "solve", background=False, timeout=600),
    )
    assert resp["status"] == "success", resp
    result = resp["result"]
    assert result["status"] == "failed", result
    assert result["phase"] == "solve", result
    assert "No candidates were found" in result["error"], result


@pytest.mark.timeout(900)
def test_live_build_failure_background(live):
    result = _background_result(live, "buildfail")
    assert result["status"] == "failed", result
    assert result["phase"] == "build", result
    assert "Script failed" in result["error"], result
    assert "BUILD-ERROR-MARKER" in str(result["context"]), result


@pytest.mark.timeout(900)
@pytest.mark.skipif(shutil.which("conda") is not None, reason="conda already on PATH")
def test_live_specs_provide_tool_to_build_script(live):
    without = _background_result(live, "needsconda")
    assert without["status"] == "failed", without
    assert without["phase"] == "build", without

    with_conda = _background_result(live, "needsconda", specs=["conda"])
    assert with_conda["status"] == "success", with_conda


@pytest.mark.timeout(900)
def test_live_build_then_test_success(live):
    result = _background_result(live, "ok")
    assert result["status"] == "success", result
    packages = [p for p in result["packages"] if str(p).endswith(".conda")]
    assert len(result["packages"]) == 1, result
    assert len(packages) == 1, result
    package = Path(str(packages[0]))
    assert package.exists(), package

    resp = live.call(
        "rattler_build_test",
        {
            "package_file": str(package),
            "channels": ["conda-forge"],
            "working_dir": str(live.tmp),
            "background": False,
            "timeout": 600,
        },
    )
    assert resp["status"] == "success", resp
    tested = resp["result"]
    assert tested["status"] == "success", tested
    assert tested["tests_passed"] >= 1, tested
