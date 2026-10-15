"""Tests for pixi_search and pixi_exec (issue #43)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from adapters.background import BackgroundJobManager
from adapters.execution import PixiExecutionAdapter
from core.config import DEFAULT_EXEC_ALLOWLIST
from core.models import PixiExecutionContext
from core.pixi_service import PixiShellService
from pixi_task.lean_mcp_interface import LeanMCPInterface

PIXI = "/opt/fake/pixi"

SAMPLE = {
    "linux-64": [
        {
            "build": "h1280f0d_0",
            "build_number": 0,
            "name": "ocaml-menhir",
            "subdir": "linux-64",
            "version": "20230608",
            "channel": "https://conda.anaconda.org/conda-forge/",
            "fn": "ocaml-menhir-20230608-h1280f0d_0.conda",
        }
    ]
}


def _adapter() -> PixiExecutionAdapter:
    adapter = PixiExecutionAdapter(MagicMock(), MagicMock(), MagicMock())
    adapter.jobs = MagicMock()
    return adapter


def _ctx(tmp_path: Path, timeout: int = 300) -> PixiExecutionContext:
    return PixiExecutionContext(working_dir=str(tmp_path), pixi_executable=PIXI, timeout=timeout)


def _completed(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


# --------------------------------------------------------------------- exec


def test_exec_argv_ordering(tmp_path):
    adapter = _adapter()
    with patch("adapters.execution.run_with_group_kill", return_value=_completed("ok")) as run:
        result = adapter.exec_tool(
            "rattler-build",
            ["build", "--recipe", "."],
            ["python=3.12", "x>=1"],
            ["conda-forge", "bioconda"],
            _ctx(tmp_path, timeout=42),
        )
    assert run.call_args.args[0] == [
        PIXI,
        "exec",
        "--with",
        "python=3.12",
        "--with",
        "x>=1",
        "-c",
        "conda-forge",
        "-c",
        "bioconda",
        "rattler-build",
        "build",
        "--recipe",
        ".",
    ]
    assert run.call_args.kwargs["timeout"] == 42
    assert run.call_args.kwargs["cwd"] == str(tmp_path)
    assert result.success and result.stdout == "ok"


def test_exec_dash_args_land_after_tool(tmp_path):
    adapter = _adapter()
    with patch("adapters.execution.run_with_group_kill", return_value=_completed()) as run:
        adapter.exec_tool("grayskull", ["--version", "-h"], [], [], _ctx(tmp_path))
    assert run.call_args.args[0] == [PIXI, "exec", "grayskull", "--version", "-h"]


@pytest.mark.parametrize("bad", ["", "-x", "a\nb", "a\x00b"])
def test_exec_bad_spec_or_channel_raises(tmp_path, bad):
    adapter = _adapter()
    with patch("adapters.execution.run_with_group_kill") as run:
        with pytest.raises(ValueError):
            adapter.exec_tool("rattler-build", [], [bad], [], _ctx(tmp_path))
        with pytest.raises(ValueError):
            adapter.exec_tool("rattler-build", [], [], [bad], _ctx(tmp_path))
        with pytest.raises(ValueError):
            adapter.exec_tool_background("rattler-build", [], [bad], [], _ctx(tmp_path))
    run.assert_not_called()
    adapter.jobs.launch.assert_not_called()


def test_exec_nul_in_args_raises(tmp_path):
    with pytest.raises(ValueError):
        _adapter().exec_tool("rattler-build", ["a\x00b"], [], [], _ctx(tmp_path))


def test_exec_nonzero_exit_is_data(tmp_path):
    adapter = _adapter()
    with patch("adapters.execution.run_with_group_kill", return_value=_completed("", "bad", 3)):
        result = adapter.exec_tool("rattler-build", [], [], [], _ctx(tmp_path))
    assert not result.success and result.exit_code == 3


def test_exec_background_launches_job(tmp_path):
    adapter = _adapter()
    adapter.jobs.launch.return_value = {"job_id": "abc", "status": "running"}
    out = adapter.exec_tool_background(
        "rattler-build", ["build"], ["python"], ["conda-forge"], _ctx(tmp_path), output_file="/o"
    )
    assert out == {"job_id": "abc", "status": "running"}
    kwargs = adapter.jobs.launch.call_args.kwargs
    assert kwargs["command"] == [
        PIXI,
        "exec",
        "--with",
        "python",
        "-c",
        "conda-forge",
        "rattler-build",
        "build",
    ]
    assert kwargs["task_name"] == "exec:rattler-build"
    assert kwargs["working_dir"] == str(tmp_path)
    assert kwargs["output_file"] == "/o"


# ------------------------------------------------------------ service level


def _service(tmp_path: Path, executor=None, allowlist=None) -> PixiShellService:
    service = PixiShellService(
        pixi_executor=executor if executor is not None else MagicMock(),
        pixi_project=MagicMock(),
        logging=MagicMock(),
        validation=MagicMock(),
        default_working_dir=str(tmp_path),
    )
    if allowlist is not None:
        service._exec_allowlist = frozenset(allowlist)
    return service


def _dispatch(iface, tool, params):
    return iface.dispatch_meta_tool("execute_tool", {"tool_name": tool, "parameters": params})


def test_default_allowlist_loaded_lazily(tmp_path):
    service = _service(tmp_path)
    assert service._get_exec_allowlist() == frozenset(DEFAULT_EXEC_ALLOWLIST)


def test_allowlist_refusal_makes_no_call(tmp_path):
    executor = MagicMock()
    service = _service(tmp_path, executor)
    iface = LeanMCPInterface(MagicMock(pixi_service=service))
    with patch("adapters.execution.run_with_group_kill") as run:
        resp = _dispatch(iface, "pixi_exec", {"tool": "rm", "args": ["-rf", "/"]})
        resp_bg = _dispatch(iface, "pixi_exec", {"tool": "rm", "background": True})
    for r in (resp, resp_bg):
        assert r["status"] == "error"
        assert "allowlisted" in r["error"]
        assert "rattler-build" in r["error"]
    assert executor.mock_calls == []
    run.assert_not_called()


def test_exec_bad_working_dir_raises(tmp_path):
    service = _service(tmp_path, allowlist={"grayskull"})
    iface = LeanMCPInterface(MagicMock(pixi_service=service))
    resp = _dispatch(
        iface, "pixi_exec", {"tool": "grayskull", "working_dir": str(tmp_path / "missing")}
    )
    assert resp["status"] == "error"
    assert "directory" in resp["error"]


def test_exec_foreground_via_dispatch(tmp_path):
    adapter = _adapter()
    service = _service(tmp_path, adapter, allowlist={"grayskull"})
    iface = LeanMCPInterface(MagicMock(pixi_service=service))
    with patch("adapters.execution.run_with_group_kill", return_value=_completed("out", "", 2)):
        resp = _dispatch(
            iface, "pixi_exec", {"tool": "grayskull", "args": ["pypi", "x"], "specs": ["pip"]}
        )
    assert resp["status"] == "success"
    result = resp["result"]
    assert result["success"] is False
    assert result["exit_code"] == 2
    assert result["stdout"] == "out"
    assert result["tool"] == "grayskull"
    assert result["working_dir"] == str(tmp_path)
    assert "grayskull pypi x" in result["command_line"]
    assert {"execution_time", "stderr"} <= set(result)


# ------------------------------------------------------------------- search


def _search(tmp_path, spec="ocaml-menhir", **kw):
    return _adapter().search_packages(spec, context=_ctx(tmp_path, timeout=60), **kw)


def test_search_parses_matches(tmp_path):
    with patch(
        "adapters.execution.run_with_group_kill",
        return_value=_completed(json.dumps(SAMPLE), "WARN noise"),
    ) as run:
        out = _search(tmp_path, channels=["conda-forge"], platform=None, limit=5)
    assert run.call_args.args[0] == [
        PIXI,
        "search",
        "--json",
        "-c",
        "conda-forge",
        "ocaml-menhir",
    ]
    assert out["found"] is True
    assert out["total_matches"] == 1 and out["truncated"] is False
    assert out["spec"] == "ocaml-menhir" and out["channels"] == ["conda-forge"]
    assert out["platform"] is None
    assert out["matches"] == [
        {
            "name": "ocaml-menhir",
            "version": "20230608",
            "build": "h1280f0d_0",
            "subdir": "linux-64",
            "channel": "https://conda.anaconda.org/conda-forge/",
        }
    ]


def test_search_platform_and_cwd_isolated(tmp_path, monkeypatch):
    repo_cwd = os.getcwd()
    with patch(
        "adapters.execution.run_with_group_kill", return_value=_completed(json.dumps(SAMPLE))
    ) as run:
        _search(tmp_path, channels=["a", "b"], platform="noarch", limit=7)
    assert run.call_args.args[0] == [
        PIXI,
        "search",
        "--json",
        "-c",
        "a",
        "-c",
        "b",
        "-p",
        "noarch",
        "ocaml-menhir",
    ]
    cwd = run.call_args.kwargs["cwd"]
    assert cwd not in (repo_cwd, str(tmp_path))
    assert not Path(cwd).exists()  # temp dir cleaned up afterwards


def test_search_not_found_is_data(tmp_path):
    stderr = "WARN x\nNo packages found matching 'nope'\n"
    with patch("adapters.execution.run_with_group_kill", return_value=_completed("", stderr, 1)):
        out = _search(tmp_path, "nope", channels=["conda-forge"], platform=None, limit=5)
    assert out == {
        "found": False,
        "spec": "nope",
        "channels": ["conda-forge"],
        "platform": None,
        "matches": [],
        "total_matches": 0,
        "truncated": False,
    }


def test_search_other_failure_raises_with_stderr_tail(tmp_path):
    stderr = "\n".join(f"line{i}" for i in range(40))
    with patch("adapters.execution.run_with_group_kill", return_value=_completed("", stderr, 2)):
        with pytest.raises(RuntimeError) as ei:
            _search(tmp_path, channels=["conda-forge"], platform=None, limit=5)
    assert "line39" in str(ei.value) and "line0\n" not in str(ei.value)


def test_search_timeout_raises(tmp_path):
    with patch(
        "adapters.execution.run_with_group_kill",
        side_effect=subprocess.TimeoutExpired("pixi", 1),
    ):
        with pytest.raises(RuntimeError):
            _search(tmp_path, channels=["conda-forge"], platform=None, limit=5)


def test_search_unparseable_stdout_raises(tmp_path):
    with patch("adapters.execution.run_with_group_kill", return_value=_completed("not json")):
        with pytest.raises(RuntimeError):
            _search(tmp_path, channels=["conda-forge"], platform=None, limit=5)


def test_search_caps_matches(tmp_path):
    rec = SAMPLE["linux-64"][0]
    big = {"linux-64": [dict(rec, version=str(i)) for i in range(40)]}
    with patch("adapters.execution.run_with_group_kill", return_value=_completed(json.dumps(big))):
        out = _search(tmp_path, channels=["conda-forge"], platform=None, limit=50)
    assert len(out["matches"]) == 25
    assert out["total_matches"] == 40
    assert out["truncated"] is True


def test_search_limit_is_newest_versions_per_subdir_and_name(tmp_path):
    rec = SAMPLE["linux-64"][0]
    payload = {
        "noarch": [dict(rec, subdir="noarch", version="9", timestamp=5)],
        "linux-64": [
            dict(rec, name="zeta", version="1", timestamp=1),
            dict(rec, name="alpha", version="old", timestamp=10),
            dict(rec, name="alpha", version="new", timestamp=30),
            dict(rec, name="alpha", version="mid", timestamp=20),
            dict(rec, name="alpha", version="none"),  # missing timestamp sorts last
        ],
    }
    with patch(
        "adapters.execution.run_with_group_kill", return_value=_completed(json.dumps(payload))
    ):
        out = _search(tmp_path, channels=["conda-forge"], platform=None, limit=2)
    got = [(m["subdir"], m["name"], m["version"]) for m in out["matches"]]
    assert got == [
        ("linux-64", "alpha", "new"),
        ("linux-64", "alpha", "mid"),
        ("linux-64", "zeta", "1"),
        ("noarch", "ocaml-menhir", "9"),
    ]
    assert out["total_matches"] == 4 and out["truncated"] is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"spec": ""},
        {"spec": "-x"},
        {"spec": "a\nb"},
        {"spec": "a\x00b"},
        {"channels": [""]},
        {"channels": ["-c"]},
        {"platform": "linux 64"},
        {"platform": "-p"},
        {"limit": 0},
        {"limit": 51},
    ],
)
def test_search_validation(tmp_path, kwargs):
    params = {"spec": "numpy", "channels": ["conda-forge"], "platform": None, "limit": 5}
    params.update(kwargs)
    spec = params.pop("spec")
    with patch("adapters.execution.run_with_group_kill") as run:
        with pytest.raises(ValueError):
            _adapter().search_packages(spec, context=_ctx(tmp_path), **params)
    run.assert_not_called()


def test_search_via_dispatch_defaults(tmp_path):
    adapter = _adapter()
    service = _service(tmp_path, adapter)
    iface = LeanMCPInterface(MagicMock(pixi_service=service))
    with patch(
        "adapters.execution.run_with_group_kill", return_value=_completed(json.dumps(SAMPLE))
    ) as run:
        resp = _dispatch(iface, "pixi_search", {"spec": "ocaml-menhir"})
    assert resp["status"] == "success"
    assert resp["result"]["found"] is True
    argv = run.call_args.args[0]
    assert argv[-1] == "ocaml-menhir"
    assert argv[argv.index("-c") + 1] == "conda-forge"
    assert "-l" not in argv and "--limit" not in argv


def test_search_via_dispatch_error_is_outer_error(tmp_path):
    service = _service(tmp_path, _adapter())
    iface = LeanMCPInterface(MagicMock(pixi_service=service))
    with patch("adapters.execution.run_with_group_kill", return_value=_completed("", "boom", 2)):
        resp = _dispatch(iface, "pixi_search", {"spec": "numpy"})
    assert resp["status"] == "error"
    assert "boom" in resp["error"]


def test_registry_entries():
    iface = LeanMCPInterface(MagicMock())
    search = iface.tool_registry["pixi_search"]
    exec_ = iface.tool_registry["pixi_exec"]
    assert (search["complexity"], search["domain"]) == ("core", "package")
    assert (exec_["complexity"], exec_["domain"]) == ("extended", "exec")
    assert search["schema"]["required"] == ["spec"]
    assert exec_["schema"]["required"] == ["tool"]
    assert "pixi_wait" in exec_["description"] and "background" in exec_["description"]
    assert "pixi_exec" in iface.tool_registry["pixi_task_status"]["description"]
    assert "pixi_exec" in iface.tool_registry["pixi_wait"]["description"]


# ------------------------------------------------------------- end to end


def test_background_exec_end_to_end(tmp_path, monkeypatch):
    fake = tmp_path / "fakepixi"
    fake.write_text('#!/bin/sh\necho "FAKEPIXI $@"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", str(fake))

    adapter = PixiExecutionAdapter(
        MagicMock(), MagicMock(), MagicMock(), BackgroundJobManager(str(tmp_path / "jobs"))
    )
    service = _service(tmp_path, adapter, allowlist={"grayskull"})
    iface = LeanMCPInterface(MagicMock(pixi_service=service))

    launched = _dispatch(
        iface,
        "pixi_exec",
        {"tool": "grayskull", "args": ["--version"], "specs": ["pip"], "background": True},
    )
    assert launched["status"] == "success", launched
    job_id = launched["result"]["job_id"]

    result = {}
    for _ in range(4):
        waited = _dispatch(
            iface,
            "pixi_wait",
            {"job_id": job_id, "wait_s": 10, "result_contains": ["FAKEPIXI exec"]},
        )
        assert waited["status"] == "success", waited
        result = waited["result"]
        if result["state"] == "done":
            break
    assert result["state"] == "done"
    assert result["exit_code"] == 0
    assert result["matched_lines"]
    assert "FAKEPIXI exec --with pip grayskull --version" in result["matched_lines"][0]


# ---------------------------------------------------------------- network


@pytest.mark.integration
def test_live_search_ocaml_menhir(tmp_path):
    service = _service(tmp_path, PixiExecutionAdapter(MagicMock(), MagicMock(), MagicMock()))
    result = service.search_packages("ocaml-menhir 20230608.*")
    assert result["found"] is True
    assert result["matches"]


@pytest.mark.integration
def test_live_search_platform_filter(tmp_path):
    service = _service(tmp_path, PixiExecutionAdapter(MagicMock(), MagicMock(), MagicMock()))
    result = service.search_packages("ocaml-menhir 20230608.*", platform="linux-64")
    assert result["found"] is True
    assert result["matches"]
    assert all(m["subdir"] == "linux-64" for m in result["matches"])
