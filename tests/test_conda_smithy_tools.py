"""Tests for conda_smithy_lint / conda_smithy_rerender / conda_smithy_rerender_result (#44).

A fake ``pixi`` (PIXI_TASK_PIXI_BIN) dispatches on ``exec conda-smithy <sub>`` so the
real adapter, BackgroundJobManager, git snapshotting and dispatch envelope are exercised.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from adapters.background import BackgroundJobManager
from adapters.execution import PixiExecutionAdapter
from core.pixi_service import PixiShellService
from pixi_task.lean_mcp_interface import LeanMCPInterface

LINT_SAMPLE = (
    "recipe has some lint:\n"
    "  The license item is expected in the about section.\n"
    "  The recipe must have some tests.\n"
    "recipe also has some suggestions:\n"
    "  Consider X.\n"
)

FAKE_PIXI = """#!/bin/sh
D="{d}"
echo "CWD=$(pwd) ARGS=$@" >> "$D/argv.log"
case "$2 $3" in
"conda-smithy --version")
  echo 2026.9.23 ;;
"conda-smithy rerender")
  mode=$(cat "$D/mode")
  case "$mode" in
    noop) echo "nothing to do" ;;
    modify) echo changed >> .ci_support/linux_64_.yaml; echo "rerendered" ;;
    slow) sleep 2; echo changed >> .ci_support/linux_64_.yaml; echo "rerendered" ;;
    commit)
      echo changed >> .ci_support/linux_64_.yaml
      git add -A
      git commit -q -m "MNT: Re-rendered"
      echo "committed" ;;
    many)
      i=0
      while [ $i -lt 80 ]; do
        echo x > ".ci_support/linux_64_c_compiler_version13cxx_compiler_version13numpy2python3.12.____cpython_v$i.yaml"
        i=$((i+1))
      done
      echo "rerendered" ;;
    fail) echo "Missing token" >&2; exit 1 ;;
  esac ;;
"conda-smithy recipe-lint")
  cat "$D/lint_out"
  exit $(cat "$D/lint_exit") ;;
esac
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _make_feedstock(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "conda-forge.yml").write_text("{}\n")
    (root / ".ci_support").mkdir()
    (root / ".ci_support" / "linux_64_.yaml").write_text("a: 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    fake = tmp_path / "fakepixi"
    fake.write_text(FAKE_PIXI.format(d=fake_dir))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PIXI_TASK_PIXI_BIN", str(fake))
    (fake_dir / "mode").write_text("noop")
    (fake_dir / "lint_out").write_text("recipe is in fine form\n")
    (fake_dir / "lint_exit").write_text("0")

    feedstock = _make_feedstock(tmp_path / "feedstock")
    recipe = tmp_path / "recipe"
    recipe.mkdir()

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

    return SimpleNamespace(
        tmp=tmp_path,
        feedstock=feedstock,
        recipe=recipe,
        iface=iface,
        call=call,
        mode=lambda m: (fake_dir / "mode").write_text(m),
        lint=lambda out, code: (
            (fake_dir / "lint_out").write_text(out),
            (fake_dir / "lint_exit").write_text(str(code)),
        ),
        argv_log=lambda: (fake_dir / "argv.log").read_text().splitlines(),
    )


# ------------------------------------------------------------------ rerender


def test_smithy_rerender_clean(env):
    resp = env.call("conda_smithy_rerender", {"feedstock_dir": str(env.feedstock)})
    assert resp["status"] == "success", resp
    result = resp["result"]
    assert result["status"] == "rerendered"
    assert result["changed_files"] == []
    assert result["total_changed"] == 0 and result["truncated"] is False
    assert result["committed"] is False
    assert result["head_before"] == result["head_after"]
    assert result["conda_smithy_version"] == "2026.9.23"
    assert result["exit_code"] == 0
    assert result["feedstock_dir"] == str(env.feedstock)
    assert "execution_time" in result
    rerender_line = [ln for ln in env.argv_log() if "conda-smithy rerender" in ln][0]
    assert f"CWD={env.feedstock}" in rerender_line
    assert f"exec conda-smithy rerender --feedstock_directory {env.feedstock}" in rerender_line
    assert "-c" not in rerender_line.split("ARGS=")[1].split()
    assert "--no-check-uptodate" not in rerender_line


def test_smithy_rerender_modifies_file(env):
    env.mode("modify")
    result = env.call("conda_smithy_rerender", {"feedstock_dir": str(env.feedstock)})["result"]
    assert result["changed_files"] == [".ci_support/linux_64_.yaml"]
    assert result["total_changed"] == 1
    assert result["committed"] is False


def test_smithy_rerender_commit_auto(env):
    env.mode("commit")
    resp = env.call(
        "conda_smithy_rerender", {"feedstock_dir": str(env.feedstock), "commit": "auto"}
    )
    result = resp["result"]
    assert result["committed"] is True
    assert result["changed_files"] == [".ci_support/linux_64_.yaml"]
    assert result["head_before"] != result["head_after"]
    assert result["head_after"] == _git(env.feedstock, "rev-parse", "HEAD").strip()
    line = [ln for ln in env.argv_log() if "conda-smithy rerender" in ln][0]
    assert "-c auto" in line


def test_smithy_rerender_no_check_uptodate_flag(env):
    env.call(
        "conda_smithy_rerender",
        {"feedstock_dir": str(env.feedstock), "no_check_uptodate": True},
    )
    line = [ln for ln in env.argv_log() if "conda-smithy rerender" in ln][0]
    assert "--no-check-uptodate" in line


def test_smithy_rerender_failure_is_outer_error(env):
    env.mode("fail")
    resp = env.call("conda_smithy_rerender", {"feedstock_dir": str(env.feedstock)})
    assert resp["status"] == "error"
    assert "Missing token" in resp["error"]


@pytest.mark.parametrize("bad", ["edit", "none-ish", "", None])
def test_smithy_rerender_bad_commit_rejected(env, bad):
    resp = env.call("conda_smithy_rerender", {"feedstock_dir": str(env.feedstock), "commit": bad})
    assert resp["status"] == "error"
    assert "commit" in resp["error"]
    assert not (env.tmp / "fake" / "argv.log").exists()  # rejected before any pixi call


def test_smithy_rerender_missing_conda_forge_yml(env):
    (env.feedstock / "conda-forge.yml").unlink()
    resp = env.call("conda_smithy_rerender", {"feedstock_dir": str(env.feedstock)})
    assert resp["status"] == "error"
    assert "conda-forge.yml" in resp["error"]


def test_smithy_rerender_non_git_dir(env):
    plain = env.tmp / "plain"
    plain.mkdir()
    (plain / "conda-forge.yml").write_text("{}\n")
    resp = env.call("conda_smithy_rerender", {"feedstock_dir": str(plain)})
    assert resp["status"] == "error"
    assert "git" in resp["error"]


def test_smithy_rerender_missing_dir(env):
    resp = env.call("conda_smithy_rerender", {"feedstock_dir": str(env.tmp / "nope")})
    assert resp["status"] == "error"


def _wait_done(env, job_id):
    result = {}
    for _ in range(6):
        waited = env.call("pixi_wait", {"job_id": job_id, "wait_s": 10})
        assert waited["status"] == "success", waited
        result = waited["result"]
        if result["state"] == "done":
            return result
    return result


def test_smithy_rerender_background_roundtrip(env):
    env.mode("slow")
    launched = env.call(
        "conda_smithy_rerender", {"feedstock_dir": str(env.feedstock), "background": True}
    )
    assert launched["status"] == "success", launched
    handle = launched["result"]
    job_id = handle["job_id"]
    assert handle["before_head"] == _git(env.feedstock, "rev-parse", "HEAD").strip()
    assert "conda_smithy_rerender_result" in handle["next"]
    assert (env.tmp / "jobs" / job_id / "rerender_before.json").is_file()

    running = env.call("conda_smithy_rerender_result", {"job_id": job_id})
    assert running["status"] == "success"
    assert running["result"] == {"state": "running", "job_id": job_id}

    assert _wait_done(env, job_id)["state"] == "done"
    final = env.call("conda_smithy_rerender_result", {"job_id": job_id})["result"]
    assert final["status"] == "rerendered"
    assert final["job_id"] == job_id
    assert final["changed_files"] == [".ci_support/linux_64_.yaml"]
    assert final["conda_smithy_version"] == "2026.9.23"
    assert final["exit_code"] == 0
    assert final["feedstock_dir"] == str(env.feedstock)


def test_smithy_rerender_background_failure_result_is_error(env):
    env.mode("fail")
    job_id = env.call(
        "conda_smithy_rerender", {"feedstock_dir": str(env.feedstock), "background": True}
    )["result"]["job_id"]
    assert _wait_done(env, job_id)["state"] == "done"
    resp = env.call("conda_smithy_rerender_result", {"job_id": job_id})
    assert resp["status"] == "error"
    assert "Missing token" in resp["error"]


def test_smithy_rerender_result_invalid_or_unknown_job(env):
    for job_id in ("../etc", "zzzzzzzzzzzz", "0123456789ab"):
        resp = env.call("conda_smithy_rerender_result", {"job_id": job_id})
        assert resp["status"] == "error", job_id


def test_smithy_rerender_result_job_without_artifact(env):
    handle = env.call(
        "pixi_exec", {"tool": "rattler-build", "args": ["--version"], "background": True}
    )
    job_id = handle["result"]["job_id"]
    _wait_done(env, job_id)
    resp = env.call("conda_smithy_rerender_result", {"job_id": job_id})
    assert resp["status"] == "error"


def _assert_capped_report(result):
    # Must survive apply_token_limits intact: capped list, honest flags, full summary.
    assert len(result["changed_files"]) == 60
    assert not any("_truncated" in f for f in result["changed_files"])
    assert result["truncated"] is True
    assert result["total_changed"] == 80
    assert result["changed_by_dir"] == {".ci_support": 80}
    assert "_token_limited" not in result


def test_smithy_rerender_many_files_not_silently_truncated(env):
    env.mode("many")
    resp = env.call("conda_smithy_rerender", {"feedstock_dir": str(env.feedstock)})
    assert resp["status"] == "success", resp
    _assert_capped_report(resp["result"])


def test_smithy_rerender_result_many_files_not_silently_truncated(env):
    env.mode("many")
    job_id = env.call(
        "conda_smithy_rerender", {"feedstock_dir": str(env.feedstock), "background": True}
    )["result"]["job_id"]
    assert _wait_done(env, job_id)["state"] == "done"
    resp = env.call("conda_smithy_rerender_result", {"job_id": job_id})
    assert resp["status"] == "success", resp
    _assert_capped_report(resp["result"])


def test_smithy_changed_by_dir_counts_root_and_top_level(env):
    env.mode("modify")
    (env.feedstock / "README.md").write_text("dirty before\n")
    # README.md already dirty and unchanged by the run -> not counted; only the yaml.
    result = env.call("conda_smithy_rerender", {"feedstock_dir": str(env.feedstock)})["result"]
    assert result["changed_by_dir"] == {".ci_support": 1}


# ---------------------------------------------------------------------- lint


def test_smithy_lint_clean(env):
    resp = env.call("conda_smithy_lint", {"recipe_dir": str(env.recipe)})
    assert resp["status"] == "success", resp
    result = resp["result"]
    assert result["status"] == "clean"
    assert result["lints"] == [] and result["hints"] == []
    assert result["exit_code"] == 0
    assert result["recipe_dir"] == str(env.recipe)
    assert result["conda_smithy_version"] == "2026.9.23"
    line = [ln for ln in env.argv_log() if "recipe-lint" in ln][0]
    assert f"CWD={env.tmp} " in line
    assert line.endswith(f"exec conda-smithy recipe-lint --conda-forge {env.recipe}")


def test_smithy_lint_with_lint(env):
    env.lint(LINT_SAMPLE, 1)
    result = env.call("conda_smithy_lint", {"recipe_dir": str(env.recipe)})["result"]
    assert result["status"] == "lint"
    assert result["exit_code"] == 1
    assert result["lints"] == [
        "The license item is expected in the about section.",
        "The recipe must have some tests.",
    ]
    assert result["hints"] == ["Consider X."]


def test_smithy_lint_hints_only_exit_zero(env):
    env.lint("recipe also has some suggestions:\n  Consider X.\n", 0)
    result = env.call("conda_smithy_lint", {"recipe_dir": str(env.recipe)})["result"]
    assert result["status"] == "hints"
    assert result["lints"] == [] and result["hints"] == ["Consider X."]


def test_smithy_lint_options(env):
    feed = env.feedstock
    env.call(
        "conda_smithy_lint",
        {"recipe_dir": str(env.recipe), "conda_forge": False, "feedstock_dir": str(feed)},
    )
    line = [ln for ln in env.argv_log() if "recipe-lint" in ln][0]
    assert line.endswith(f"exec conda-smithy recipe-lint --feedstock-dir {feed} {env.recipe}")


def test_smithy_lint_relative_recipe_dir_resolves_against_base(env):
    result = env.call("conda_smithy_lint", {"recipe_dir": "recipe"})["result"]
    assert result["recipe_dir"] == str(env.recipe)


def test_smithy_lint_missing_recipe_dir(env):
    resp = env.call("conda_smithy_lint", {"recipe_dir": str(env.tmp / "nope")})
    assert resp["status"] == "error"
    assert "recipe_dir" in resp["error"]


def test_smithy_lint_exit_two_is_error(env):
    env.lint("Traceback: boom\n", 2)
    resp = env.call("conda_smithy_lint", {"recipe_dir": str(env.recipe)})
    assert resp["status"] == "error"
    assert "boom" in resp["error"]


def test_smithy_lint_exit_one_without_lints_is_error(env):
    env.lint("something unexpected\n", 1)
    resp = env.call("conda_smithy_lint", {"recipe_dir": str(env.recipe)})
    assert resp["status"] == "error"
    assert "something unexpected" in resp["error"]


def test_smithy_lint_unrecognised_output_is_error(env):
    env.lint("totally unparseable\n", 0)
    resp = env.call("conda_smithy_lint", {"recipe_dir": str(env.recipe)})
    assert resp["status"] == "error"


def test_smithy_lint_caps_items(env):
    items = "".join(f"  lint number {i}\n" for i in range(60))
    env.lint("recipe has some lint:\n" + items, 1)
    result = env.call("conda_smithy_lint", {"recipe_dir": str(env.recipe)})["result"]
    assert len(result["lints"]) == 50
    assert result["truncated"] is True


# ------------------------------------------------------------------ registry


def test_smithy_registry_entries():
    iface = LeanMCPInterface(MagicMock())
    for name in ("conda_smithy_lint", "conda_smithy_rerender", "conda_smithy_rerender_result"):
        entry = iface.tool_registry[name]
        assert (entry["complexity"], entry["domain"]) == ("extended", "conda-forge")
        assert entry["examples"]
    assert iface.tool_registry["conda_smithy_lint"]["schema"]["required"] == ["recipe_dir"]
    rerender = iface.tool_registry["conda_smithy_rerender"]["schema"]
    assert rerender["required"] == ["feedstock_dir"]
    assert rerender["properties"]["commit"]["enum"] == ["none", "auto"]
    assert iface.tool_registry["conda_smithy_rerender_result"]["schema"]["required"] == ["job_id"]


# ---------------------------------------------------------------------- live

ZIG_RECIPE = Path("/home/memento/PycharmProjects/Conda-Feedstocks/zig-feedstock/recipe")


@pytest.mark.integration
@pytest.mark.skipif(not ZIG_RECIPE.is_dir(), reason="zig-feedstock not available")
def test_live_smithy_lint_zig_feedstock():
    adapter = PixiExecutionAdapter(MagicMock(), MagicMock(), MagicMock())
    service = PixiShellService(
        pixi_executor=adapter,
        pixi_project=MagicMock(),
        logging=MagicMock(),
        validation=MagicMock(),
    )
    result = service.conda_smithy_lint(str(ZIG_RECIPE))
    assert result["status"] == "clean", result
