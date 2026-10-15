"""Tests for rattler_build_build / rattler_build_test / rattler_build_result (#45).

A fake ``pixi`` (PIXI_TASK_PIXI_BIN) answers ``exec rattler-build build|test`` with canned
JSON log output so the real adapter, BackgroundJobManager and dispatch envelope run.
"""

from __future__ import annotations

import stat
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from adapters.background import BackgroundJobManager
from adapters.execution import PixiExecutionAdapter
from core.pixi_service import PixiShellService
from pixi_task.lean_mcp_interface import LeanMCPInterface
from tests.test_rattler_build_log import BUILD_FAILURE, SOLVE_FAILURE, SUCCESS, TEST_FAILURE

FAKE_PIXI = """#!/bin/sh
D="{d}"
echo "CWD=$(pwd) ARGS=$@" >> "$D/argv.log"
case "$2 $3" in
"rattler-build build"|"rattler-build test")
  [ -f "$D/rb_sleep" ] && sleep "$(cat "$D/rb_sleep")"
  cat "$D/rb_out" >&2
  exit "$(cat "$D/rb_exit")" ;;
esac
"""

TOOLS = ("rattler_build_build", "rattler_build_test", "rattler_build_result")


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    fake = tmp_path / "fakepixi"
    fake.write_text(FAKE_PIXI.format(d=fake_dir))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", str(fake))
    (fake_dir / "rb_out").write_text(SUCCESS)
    (fake_dir / "rb_exit").write_text("0")

    (tmp_path / "recipe").mkdir()
    (tmp_path / "recipe" / "recipe.yaml").write_text("package: {}\n")
    (tmp_path / "variants.yaml").write_text("python: ['3.12']\n")
    (tmp_path / "pkg.conda").write_text("not really a package\n")

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

    def set_run(output, exit_code=0, sleep=None):
        (fake_dir / "rb_out").write_text(output)
        (fake_dir / "rb_exit").write_text(str(exit_code))
        if sleep is not None:
            (fake_dir / "rb_sleep").write_text(str(sleep))

    return SimpleNamespace(
        tmp=tmp_path,
        iface=iface,
        call=call,
        set_run=set_run,
        argv_lines=lambda: [
            ln.split("ARGS=")[1].split() for ln in (fake_dir / "argv.log").read_text().splitlines()
        ],
        argv_log_exists=(fake_dir / "argv.log").exists,
    )


def _wait_done(env, job_id):
    result = {}
    for _ in range(6):
        waited = env.call("pixi_wait", {"job_id": job_id, "wait_s": 10})
        assert waited["status"] == "success", waited
        result = waited["result"]
        if result["state"] == "done":
            return result
    return result


def test_discover_lists_rattler_tools(env):
    found = env.iface.dispatch_meta_tool("discover_tools", {"pattern": "rattler_build"})
    names = {t["name"] for t in found["available_tools"]}
    assert set(TOOLS) <= names


def test_registry_entries():
    iface = LeanMCPInterface(MagicMock())
    for name in TOOLS:
        assert iface.tool_registry[name]["complexity"] == "extended"
        assert iface.tool_registry[name]["examples"]
    build = iface.tool_registry["rattler_build_build"]["schema"]
    assert build["required"] == ["recipe"]
    assert build["properties"]["skip_existing"]["enum"] == ["none", "local", "all"]
    assert build["properties"]["test"]["enum"] == ["skip", "native", "native-and-emulated"]
    assert build["properties"]["variant_config"]["items"] == {"type": "string"}
    assert iface.tool_registry["rattler_build_test"]["schema"]["required"] == ["package_file"]
    assert iface.tool_registry["rattler_build_result"]["schema"]["required"] == ["job_id"]


# ---------------------------------------------------------------- build flow


def test_background_build_solve_failure_roundtrip(env):
    env.set_run(SOLVE_FAILURE, 1)
    launched = env.call("rattler_build_build", {"recipe": "recipe"})
    assert launched["status"] == "success", launched
    handle = launched["result"]
    job_id = handle["job_id"]
    assert "rattler_build_result" in handle["next"]
    assert (env.tmp / "jobs" / job_id / "rattler_build.json").is_file()

    assert _wait_done(env, job_id)["state"] == "done"
    resp = env.call("rattler_build_result", {"job_id": job_id})
    assert resp["status"] == "success", resp
    result = resp["result"]
    assert result["status"] == "failed"
    assert result["phase"] == "solve"
    assert "No candidates were found" in result["error"]
    assert result["exit_code"] == 1
    assert result["job_id"] == job_id
    assert result["command"] == "build"
    assert result["output_file"].endswith("output.log")
    assert "_token_limited" not in result


def test_foreground_build_success(env):
    env.set_run(SUCCESS, 0)
    resp = env.call("rattler_build_build", {"recipe": "recipe", "background": False})
    assert resp["status"] == "success", resp
    result = resp["result"]
    assert result["status"] == "success"
    assert result["packages"]
    assert result["command"] == "build"
    assert result["working_dir"] == str(env.tmp)
    assert "execution_time" in result
    assert "background=true" in result["note"]
    assert "_token_limited" not in result


def test_foreground_build_failure_is_data(env):
    env.set_run(BUILD_FAILURE, 1)
    resp = env.call("rattler_build_build", {"recipe": "recipe", "background": False})
    assert resp["status"] == "success", resp
    assert resp["result"]["status"] == "failed"
    assert resp["result"]["phase"] == "build"


def test_build_argv_assembly(env):
    env.call(
        "rattler_build_build",
        {
            "recipe": "recipe",
            "variant_config": ["variants.yaml", str(env.tmp / "recipe")],
            "target_platform": "linux-aarch64",
            "output_dir": "out",
            "channels": ["conda-forge", "local"],
            "skip_existing": "local",
            "test": "native",
            "extra_args": ["--no-include-recipe", "--keep-build"],
            "background": False,
        },
    )
    assert env.argv_lines() == [
        [
            "exec",
            "rattler-build",
            "build",
            "--recipe",
            "recipe",
            "--log-style",
            "json",
            "-m",
            "variants.yaml",
            "-m",
            str(env.tmp / "recipe"),
            "--target-platform",
            "linux-aarch64",
            "--output-dir",
            "out",
            "-c",
            "conda-forge",
            "-c",
            "local",
            "--skip-existing",
            "local",
            "--test",
            "native",
            "--no-include-recipe",
            "--keep-build",
        ]
    ]


def test_build_minimal_argv_has_single_log_style(env):
    env.call("rattler_build_build", {"recipe": "recipe", "background": False})
    (argv,) = env.argv_lines()
    assert argv == ["exec", "rattler-build", "build", "--recipe", "recipe", "--log-style", "json"]


@pytest.mark.parametrize(
    ("params", "needle"),
    [
        ({"recipe": "nope"}, "recipe"),
        (
            {"recipe": "recipe", "variant_config": ["variants.yaml", "missing.yaml"]},
            "variant_config",
        ),
        ({"recipe": "recipe", "skip_existing": "sometimes"}, "skip_existing"),
        ({"recipe": "recipe", "test": "maybe"}, "test"),
        ({"recipe": "recipe", "extra_args": ["--log-style", "plain"]}, "--log-style"),
        ({"recipe": "recipe", "extra_args": ["--log-style=fancy"]}, "--log-style"),
        ({"recipe": "recipe", "extra_args": "--keep-build"}, "extra_args"),
        ({"recipe": "recipe", "extra_args": [1]}, "extra_args"),
        ({"recipe": "recipe", "working_dir": "no-such-dir"}, "working_dir"),
    ],
)
def test_build_validation_errors(env, params, needle):
    resp = env.call("rattler_build_build", params)
    assert resp["status"] == "error", resp
    assert needle in resp["error"]
    assert not env.argv_log_exists()  # rejected before any pixi call


def test_test_validation_errors(env):
    missing = env.call("rattler_build_test", {"package_file": "missing.conda"})
    assert missing["status"] == "error" and "package_file" in missing["error"]
    directory = env.call("rattler_build_test", {"package_file": "recipe"})
    assert directory["status"] == "error"
    bad = env.call(
        "rattler_build_test", {"package_file": "pkg.conda", "extra_args": ["--log-style=plain"]}
    )
    assert bad["status"] == "error" and "--log-style" in bad["error"]
    assert not env.argv_log_exists()


# ----------------------------------------------------------------- test flow


def test_background_test_failure_roundtrip(env):
    env.set_run(TEST_FAILURE, 1)
    launched = env.call(
        "rattler_build_test", {"package_file": "pkg.conda", "channels": ["conda-forge"]}
    )
    assert launched["status"] == "success", launched
    job_id = launched["result"]["job_id"]
    assert _wait_done(env, job_id)["state"] == "done"
    result = env.call("rattler_build_result", {"job_id": job_id})["result"]
    assert result["status"] == "failed"
    assert result["phase"] == "test"
    assert result["command"] == "test"
    (argv,) = env.argv_lines()
    assert argv == [
        "exec",
        "rattler-build",
        "test",
        "--package-file",
        "pkg.conda",
        "--log-style",
        "json",
        "-c",
        "conda-forge",
    ]


def test_foreground_test_success(env):
    env.set_run(SUCCESS, 0)
    resp = env.call("rattler_build_test", {"package_file": "pkg.conda", "background": False})
    assert resp["status"] == "success", resp
    assert resp["result"]["command"] == "test"
    assert resp["result"]["status"] == "success"


# ------------------------------------------------------------------- result


def test_result_on_non_rattler_job_is_error(env):
    handle = env.call(
        "pixi_exec", {"tool": "rattler-build", "args": ["--version"], "background": True}
    )
    job_id = handle["result"]["job_id"]
    _wait_done(env, job_id)
    resp = env.call("rattler_build_result", {"job_id": job_id})
    assert resp["status"] == "error"
    assert "not a rattler_build" in resp["error"]


def test_result_invalid_or_unknown_job(env):
    for job_id in ("../etc", "zzzzzzzzzzzz", "0123456789ab"):
        assert env.call("rattler_build_result", {"job_id": job_id})["status"] == "error", job_id


def test_result_on_running_job_reports_running(env):
    env.set_run(SUCCESS, 0, sleep=2)
    job_id = env.call("rattler_build_build", {"recipe": "recipe"})["result"]["job_id"]
    running = env.call("rattler_build_result", {"job_id": job_id})
    assert running["status"] == "success"
    assert running["result"] == {"state": "running", "job_id": job_id}
    assert _wait_done(env, job_id)["state"] == "done"
    done = env.call("rattler_build_result", {"job_id": job_id})["result"]
    assert done["status"] == "success"
    assert done["packages"]


def test_result_context_lines_is_honoured(env):
    env.set_run(BUILD_FAILURE, 1)
    job_id = env.call("rattler_build_build", {"recipe": "recipe"})["result"]["job_id"]
    _wait_done(env, job_id)
    few = env.call("rattler_build_result", {"job_id": job_id, "context_lines": 2})["result"]
    many = env.call("rattler_build_result", {"job_id": job_id, "context_lines": 20})["result"]
    assert len(few["context"].splitlines()) <= 2
    assert len(many["context"].splitlines()) >= len(few["context"].splitlines())


def test_result_survives_deleted_output_file(env):
    env.set_run(SUCCESS, 0)
    out = env.tmp / "custom.log"
    job_id = env.call("rattler_build_build", {"recipe": "recipe", "output_file": str(out)})[
        "result"
    ]["job_id"]
    _wait_done(env, job_id)
    time.sleep(0.1)
    out.unlink()
    resp = env.call("rattler_build_result", {"job_id": job_id})
    assert resp["status"] == "success", resp
    assert resp["result"]["output_file"] == str(out)
