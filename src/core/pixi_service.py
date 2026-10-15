"""
Core business logic for Pixi Shell MCP Server.

This module implements the secure pixi task execution service,
providing thread-safe operations with comprehensive validation.
"""

import os
import time
from pathlib import Path
from typing import Any

from core.conda_smithy import (
    MAX_CHANGED_FILES,
    MAX_LINT_ITEMS,
    count_by_top_dir,
    output_tail,
    parse_recipe_lint,
)
from core.rattler_build_log import summarize_build_log

from core.config import load_exec_allowlist
from core.models import (
    PixiExecutionContext,
)
from core.ports import (
    PixiExecutorPort,
    PixiProjectPort,
    LoggingPort,
    ValidationPort,
)

RERENDER_BEFORE_ARTIFACT = "rerender_before.json"
RATTLER_BUILD_ARTIFACT = "rattler_build.json"
RATTLER_SKIP_EXISTING = ("none", "local", "all")
RATTLER_TEST_MODES = ("skip", "native", "native-and-emulated")


class PixiShellService:
    """
    Core service for secure pixi task execution.

    Provides thread-safe operations with comprehensive validation,
    environment management, and task execution.
    """

    def __init__(
        self,
        pixi_executor: PixiExecutorPort,
        pixi_project: PixiProjectPort,
        logging: LoggingPort,
        validation: ValidationPort,
        default_working_dir: str | None = None,
    ):
        self.pixi_executor = pixi_executor
        self.pixi_project = pixi_project
        self.logging = logging
        self.validation = validation
        # Base directory used to resolve relative/omitted working_dir values.
        # An MCP server's process CWD is unrelated to the caller's project, so
        # callers pass an absolute working_dir per call. When omitted we fall
        # back to this configured base (the launch --repository), or os.getcwd()
        # when no base was configured. We deliberately do NOT os.chdir at startup.
        self.default_working_dir = default_working_dir
        self._exec_allowlist: frozenset[str] | None = None

    def _resolve_working_dir(self, working_dir: str | None) -> str:
        """Resolve a caller-supplied working_dir to a usable directory path.

        - ``None``        -> the configured base (default_working_dir) or os.getcwd()
        - absolute path   -> used as-is
        - relative path   -> resolved against the configured base / os.getcwd()

        The server process is never ``chdir``-ed, so relative paths resolve
        against the configured project base rather than the server's install dir.
        """
        base = self.default_working_dir or os.getcwd()
        if working_dir is None:
            return base
        path = Path(working_dir)
        if path.is_absolute():
            return working_dir
        return str(Path(base) / path)

    def run_task(
        self,
        task_name: str,
        args: list[str] | None = None,
        working_dir: str | None = None,
        timeout: int = 300,
        environment: str | None = None,
        manifest_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a pixi task with arguments.

        Returns: {"success": bool, "stdout": str, "stderr": str, "exit_code": int, "execution_time": float}
        """
        start_time = time.time()
        working_dir = self._resolve_working_dir(working_dir)

        try:
            # Determine which directory has the pixi project (manifest_path or working_dir)
            project_dir = str(Path(manifest_path).parent) if manifest_path else working_dir

            # Validate pixi project
            if not self.pixi_project.is_pixi_project(project_dir):
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Directory {project_dir} is not a pixi project (no pixi.toml found)",
                    "exit_code": 1,
                    "execution_time": time.time() - start_time,
                    "task_name": task_name,
                    "working_dir": working_dir,
                }

            # Create execution context
            context = PixiExecutionContext(
                working_dir=working_dir,
                timeout=timeout,
                capture_output=True,
                environment=environment,
                manifest_path=manifest_path,
            )

            # Execute task
            result = self.pixi_executor.run_task(task_name, args or [], context)

            self.logging.log_info(
                f"Pixi task executed: {task_name}",
                {
                    "success": result.success,
                    "exit_code": result.exit_code,
                    "execution_time": result.execution_time,
                    "working_dir": working_dir,
                },
            )

            return {
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "execution_time": result.execution_time,
                "task_name": result.task_name,
                "working_dir": result.working_dir,
                "command_line": result.command_line,
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Task execution failed: {str(e)}"

            self.logging.log_error(
                error_msg,
                {
                    "task_name": task_name,
                    "args": args,
                    "working_dir": working_dir,
                    "error": str(e),
                },
            )

            return {
                "success": False,
                "stdout": "",
                "stderr": error_msg,
                "exit_code": 1,
                "execution_time": execution_time,
                "task_name": task_name,
                "working_dir": working_dir,
            }

    def run_task_background(
        self,
        task_name: str,
        args: list[str] | None = None,
        working_dir: str | None = None,
        environment: str | None = None,
        manifest_path: str | None = None,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Launch a pixi task in the background and return a job handle.

        For long-running tasks (e.g. a full pytest suite) that would otherwise
        exceed the MCP transport window. Poll completion via get_job_status().
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            project_dir = str(Path(manifest_path).parent) if manifest_path else working_dir

            if not self.pixi_project.is_pixi_project(project_dir):
                return {
                    "status": "error",
                    "task_name": task_name,
                    "working_dir": working_dir,
                    "error": f"Directory {project_dir} is not a pixi project (no pixi.toml found)",
                }

            context = PixiExecutionContext(
                working_dir=working_dir,
                capture_output=True,
                environment=environment,
                manifest_path=manifest_path,
            )

            result = self.pixi_executor.run_task_background(
                task_name, args or [], context, output_file=output_file
            )

            self.logging.log_info(
                f"Pixi task launched in background: {task_name}",
                {
                    "job_id": result.get("job_id"),
                    "status": result.get("status"),
                    "working_dir": working_dir,
                },
            )
            return result

        except Exception as e:
            error_msg = f"Background task launch failed: {str(e)}"
            self.logging.log_error(
                error_msg,
                {
                    "task_name": task_name,
                    "args": args,
                    "working_dir": working_dir,
                    "error": str(e),
                },
            )
            return {
                "status": "error",
                "task_name": task_name,
                "working_dir": working_dir,
                "error": error_msg,
            }

    def _get_exec_allowlist(self) -> frozenset[str]:
        """Load the pixi_exec allowlist once from the server's own pyproject."""
        if self._exec_allowlist is None:
            self._exec_allowlist = load_exec_allowlist()
        return self._exec_allowlist

    def exec_tool(
        self,
        tool: str,
        args: list[str] | None = None,
        specs: list[str] | None = None,
        channels: list[str] | None = None,
        working_dir: str | None = None,
        timeout: int = 300,
        background: bool = False,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Run an allowlisted tool via ``pixi exec`` (foreground or background).

        Refusals and invalid input raise ValueError; a command that ran and
        exited non-zero is returned as data.
        """
        allowed = self._get_exec_allowlist()
        if tool not in allowed:
            raise ValueError(
                f"pixi_exec: tool {tool!r} is not allowlisted. Allowed: {sorted(allowed)}. "
                "Configure [tool.pixi-task].exec_allowlist in the pixi-task server's pyproject.toml."
            )

        resolved_dir = self._resolve_working_dir(working_dir)
        if not Path(resolved_dir).is_dir():
            raise ValueError(
                f"pixi_exec: working_dir {resolved_dir!r} is not an existing directory"
            )

        context = PixiExecutionContext(
            working_dir=resolved_dir, timeout=timeout, capture_output=True
        )
        if background:
            result = self.pixi_executor.exec_tool_background(
                tool, args or [], specs or [], channels or [], context, output_file=output_file
            )
            self.logging.log_info(
                f"pixi exec launched in background: {tool}",
                {"job_id": result.get("job_id"), "working_dir": resolved_dir},
            )
            return result

        task_result = self.pixi_executor.exec_tool(
            tool, args or [], specs or [], channels or [], context
        )
        self.logging.log_info(
            f"pixi exec executed: {tool}",
            {"exit_code": task_result.exit_code, "working_dir": resolved_dir},
        )
        return {
            "success": task_result.success,
            "stdout": task_result.stdout,
            "stderr": task_result.stderr,
            "exit_code": task_result.exit_code,
            "execution_time": task_result.execution_time,
            "tool": tool,
            "working_dir": task_result.working_dir,
            "command_line": task_result.command_line,
        }

    def search_packages(
        self,
        spec: str,
        channels: list[str] | None = None,
        platform: str | None = None,
        limit: int = 5,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Search conda channels via ``pixi search``; see PixiExecutorPort.search_packages."""
        context = PixiExecutionContext(
            working_dir=self._resolve_working_dir(None), timeout=timeout, capture_output=True
        )
        return self.pixi_executor.search_packages(
            spec,
            ["conda-forge"] if channels is None else channels,
            platform,
            limit,
            context,
        )

    # ----- conda-smithy tools (issue #44) -----------------------------------
    # These call `pixi exec conda-smithy ...` directly through the executor port.
    # They are NOT subject to the pixi_exec allowlist: each dedicated tool is its
    # own permission. A failed conda-smithy run raises (outer status "error").

    def _smithy_context(self, cwd: str, timeout: int) -> PixiExecutionContext:
        return PixiExecutionContext(working_dir=cwd, timeout=timeout, capture_output=True)

    def _resolve_existing_dir(self, tool: str, label: str, value: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{tool}: {label} must be a non-empty string")
        path = os.path.normpath(self._resolve_working_dir(value))
        if not Path(path).is_dir():
            raise ValueError(f"{tool}: {label} {path!r} is not an existing directory")
        return path

    def _smithy_version(self, context: PixiExecutionContext) -> str:
        result = self.pixi_executor.run_pixi_exec(["conda-smithy", "--version"], context)
        if not result.success:
            raise RuntimeError(
                f"conda-smithy --version failed (exit {result.exit_code}): "
                f"{output_tail(result.stdout, result.stderr)}"
            )
        return result.stdout.strip()

    def conda_smithy_lint(
        self,
        recipe_dir: str,
        conda_forge: bool = True,
        feedstock_dir: str | None = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Run ``conda-smithy recipe-lint`` and return parsed lints/hints."""
        recipe = self._resolve_existing_dir("conda_smithy_lint", "recipe_dir", recipe_dir)
        argv = ["conda-smithy", "recipe-lint"]
        if conda_forge:
            argv.append("--conda-forge")
        if feedstock_dir is not None:
            feedstock = self._resolve_existing_dir(
                "conda_smithy_lint", "feedstock_dir", feedstock_dir
            )
            argv.extend(["--feedstock-dir", feedstock])
        argv.append(recipe)

        context = self._smithy_context(os.path.dirname(recipe), timeout)
        version = self._smithy_version(context)
        result = self.pixi_executor.run_pixi_exec(argv, context)
        parsed = parse_recipe_lint(result.stdout)
        lints, hints = parsed["lints"], parsed["hints"]

        failure = None
        if result.exit_code not in (0, 1):
            failure = "conda-smithy recipe-lint failed"
        elif result.exit_code == 1 and not lints:
            failure = "conda-smithy recipe-lint exited 1 without reporting lint"
        elif result.exit_code == 0 and not (lints or hints or parsed["fine"]):
            failure = "conda-smithy recipe-lint produced unrecognised output"
        if failure:
            raise RuntimeError(
                f"{failure} (exit {result.exit_code}): {output_tail(result.stdout, result.stderr)}"
            )

        if lints:
            status = "lint"
        elif hints:
            status = "hints"
        else:
            status = "clean"
        return {
            "status": status,
            "lints": lints[:MAX_LINT_ITEMS],
            "hints": hints[:MAX_LINT_ITEMS],
            "truncated": len(lints) > MAX_LINT_ITEMS or len(hints) > MAX_LINT_ITEMS,
            "exit_code": result.exit_code,
            "recipe_dir": recipe,
            "conda_smithy_version": version,
        }

    def _validated_feedstock(self, feedstock_dir: str) -> str:
        tool = "conda_smithy_rerender"
        path = self._resolve_existing_dir(tool, "feedstock_dir", feedstock_dir)
        if not (Path(path) / "conda-forge.yml").is_file():
            raise ValueError(f"{tool}: {path!r} has no conda-forge.yml (not a feedstock)")
        if not self.pixi_executor.git_is_work_tree(path):
            raise ValueError(f"{tool}: {path!r} is not a git work tree")
        return path

    def _rerender_report(
        self,
        feedstock: str,
        before: dict[str, Any],
        version: str,
        exit_code: int,
        execution_time: float | None,
    ) -> dict[str, Any]:
        changed = self.pixi_executor.git_changed_since(feedstock, before)
        head_after = self.pixi_executor.git_head(feedstock)
        return {
            "status": "rerendered",
            "changed_files": changed[:MAX_CHANGED_FILES],
            "total_changed": len(changed),
            "truncated": len(changed) > MAX_CHANGED_FILES,
            "changed_by_dir": count_by_top_dir(changed),
            "committed": head_after != before["head"],
            "head_before": before["head"],
            "head_after": head_after,
            "conda_smithy_version": version,
            "exit_code": exit_code,
            "execution_time": execution_time,
            "feedstock_dir": feedstock,
        }

    def conda_smithy_rerender(
        self,
        feedstock_dir: str,
        commit: str = "none",
        no_check_uptodate: bool = False,
        timeout: int = 600,
        background: bool = False,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Run ``conda-smithy rerender`` and report which files changed (never the full log)."""
        if commit not in ("none", "auto"):
            raise ValueError(
                f"conda_smithy_rerender: commit must be 'none' or 'auto', got {commit!r}"
            )
        feedstock = self._validated_feedstock(feedstock_dir)

        argv = ["conda-smithy", "rerender", "--feedstock_directory", feedstock]
        if commit == "auto":
            argv.extend(["-c", "auto"])
        if no_check_uptodate:
            argv.append("--no-check-uptodate")

        context = self._smithy_context(feedstock, timeout)
        version = self._smithy_version(context)
        before = self.pixi_executor.git_snapshot(feedstock)

        if background:
            launch = self.pixi_executor.launch_pixi_exec_background(
                argv, context, "conda-smithy:rerender", output_file
            )
            if launch.get("status") == "error" or not launch.get("job_id"):
                raise RuntimeError(f"conda-smithy rerender launch failed: {launch.get('error')}")
            self.pixi_executor.write_job_artifact(
                launch["job_id"],
                RERENDER_BEFORE_ARTIFACT,
                {
                    "before": before,
                    "feedstock_dir": feedstock,
                    "conda_smithy_version": version,
                    "commit": commit,
                },
            )
            return {
                **launch,
                "before_head": before["head"],
                "next": "pixi_wait(job_id) then conda_smithy_rerender_result(job_id)",
            }

        result = self.pixi_executor.run_pixi_exec(argv, context)
        if not result.success:
            raise RuntimeError(
                f"conda-smithy rerender failed (exit {result.exit_code}): "
                f"{output_tail(result.stdout, result.stderr)}"
            )
        return self._rerender_report(
            feedstock, before, version, result.exit_code, result.execution_time
        )

    def conda_smithy_rerender_result(self, job_id: str, tail_lines: int = 30) -> dict[str, Any]:
        """Report the outcome of a background ``conda_smithy_rerender`` job."""
        artifact = self.pixi_executor.read_job_artifact(job_id, RERENDER_BEFORE_ARTIFACT)
        if artifact is None:
            raise ValueError(f"Job {job_id!r} is not a conda_smithy_rerender background job")

        status = self.pixi_executor.get_job_status(job_id, tail_lines)
        state = status.get("status")
        if state == "running" or (state == "unknown" and status.get("retryable")):
            return {"state": "running", "job_id": job_id}
        if state != "completed":
            raise RuntimeError(status.get("error") or f"Job {job_id} is in state {state!r}")
        if status.get("exit_code") != 0:
            raise RuntimeError(
                f"conda-smithy rerender failed (exit {status.get('exit_code')}): "
                f"{output_tail(status.get('output_tail', ''), '', tail_lines)}"
            )
        report = self._rerender_report(
            artifact["feedstock_dir"],
            artifact["before"],
            artifact["conda_smithy_version"],
            0,
            status.get("execution_time"),
        )
        return {**report, "job_id": job_id}

    # ----- rattler-build tools (issue #45) ----------------------------------
    # Like the smithy tools these call `pixi exec rattler-build ...` directly (not
    # subject to the pixi_exec allowlist). A failed build/test is DATA: the filtered
    # summary comes back with status "failed". ValueError means bad parameters,
    # RuntimeError means the job could not be launched or tracked.

    @staticmethod
    def _rb_str_list(tool: str, label: str, value: list[str] | None) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{tool}: {label} must be a list of strings")
        return value

    @staticmethod
    def _rb_existing(tool: str, label: str, value: str, wd: str, *, file_only: bool) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{tool}: {label} must be a non-empty string")
        path = Path(value) if Path(value).is_absolute() else Path(wd) / value
        if not (path.is_file() if file_only else path.exists()):
            kind = "file" if file_only else "file or directory"
            raise ValueError(f"{tool}: {label} {value!r} is not an existing {kind} (in {wd})")

    def _rb_with_args(self, tool: str, specs: list[str] | None) -> list[str]:
        """Validate ``specs`` and expand them to ``--with <spec>`` pairs (pixi exec options)."""
        spec_list = self._rb_str_list(tool, "specs", specs)
        for spec in spec_list:
            if not spec or spec.startswith("-") or "\x00" in spec or "\n" in spec or "\r" in spec:
                raise ValueError(f"{tool}: invalid spec in specs: {spec!r}")
        return [part for spec in spec_list for part in ("--with", spec)]

    def _rb_extra_args(self, tool: str, extra_args: list[str] | None) -> list[str]:
        args = self._rb_str_list(tool, "extra_args", extra_args)
        if any(a == "--log-style" or a.startswith("--log-style=") for a in args):
            raise ValueError(
                f"{tool}: extra_args must not set --log-style (the summary needs json logs)"
            )
        return args

    def _rb_dispatch(
        self,
        command: str,
        argv: list[str],
        wd: str,
        timeout: int,
        background: bool,
        output_file: str | None,
    ) -> dict[str, Any]:
        context = PixiExecutionContext(working_dir=wd, timeout=timeout, capture_output=True)
        if not background:
            result = self.pixi_executor.run_pixi_exec(argv, context)
            return {
                **summarize_build_log(result.stdout + "\n" + result.stderr, result.exit_code),
                "command": command,
                "execution_time": result.execution_time,
                "working_dir": wd,
                "note": "foreground runs do not keep the full log; use background=true for long builds",
            }
        launch = self.pixi_executor.launch_pixi_exec_background(
            argv, context, f"rattler-build:{command}", output_file
        )
        if launch.get("status") == "error" or not launch.get("job_id"):
            raise RuntimeError(f"rattler-build {command} launch failed: {launch.get('error')}")
        self.pixi_executor.write_job_artifact(
            launch["job_id"],
            RATTLER_BUILD_ARTIFACT,
            {"command": command, "working_dir": wd, "argv": argv},
        )
        return {**launch, "next": "pixi_wait(job_id) then rattler_build_result(job_id)"}

    def rattler_build_build(
        self,
        recipe: str,
        variant_config: list[str] | None = None,
        target_platform: str | None = None,
        output_dir: str | None = None,
        channels: list[str] | None = None,
        skip_existing: str | None = None,
        test: str | None = None,
        extra_args: list[str] | None = None,
        working_dir: str = ".",
        background: bool = True,
        output_file: str | None = None,
        timeout: int = 3600,
        specs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run ``rattler-build build`` with json logs; return/launch a filtered summary."""
        tool = "rattler_build_build"
        wd = self._resolve_existing_dir(tool, "working_dir", working_dir)
        self._rb_existing(tool, "recipe", recipe, wd, file_only=False)
        variants = self._rb_str_list(tool, "variant_config", variant_config)
        for variant in variants:
            self._rb_existing(tool, "variant_config", variant, wd, file_only=False)
        if skip_existing is not None and skip_existing not in RATTLER_SKIP_EXISTING:
            raise ValueError(
                f"{tool}: skip_existing must be one of {RATTLER_SKIP_EXISTING}, got {skip_existing!r}"
            )
        if test is not None and test not in RATTLER_TEST_MODES:
            raise ValueError(f"{tool}: test must be one of {RATTLER_TEST_MODES}, got {test!r}")
        channel_list = self._rb_str_list(tool, "channels", channels)
        extra = self._rb_extra_args(tool, extra_args)
        with_args = self._rb_with_args(tool, specs)

        argv = [*with_args, "rattler-build", "build", "--recipe", recipe, "--log-style", "json"]
        for variant in variants:
            argv.extend(["-m", variant])
        for flag, value in (("--target-platform", target_platform), ("--output-dir", output_dir)):
            if value is not None:
                argv.extend([flag, value])
        for channel in channel_list:
            argv.extend(["-c", channel])
        for flag, value in (("--skip-existing", skip_existing), ("--test", test)):
            if value is not None:
                argv.extend([flag, value])
        argv.extend(extra)
        return self._rb_dispatch("build", argv, wd, timeout, background, output_file)

    def rattler_build_test(
        self,
        package_file: str,
        channels: list[str] | None = None,
        extra_args: list[str] | None = None,
        working_dir: str = ".",
        background: bool = True,
        output_file: str | None = None,
        timeout: int = 1800,
        specs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run ``rattler-build test`` on a built package; same summary shape as build."""
        tool = "rattler_build_test"
        wd = self._resolve_existing_dir(tool, "working_dir", working_dir)
        self._rb_existing(tool, "package_file", package_file, wd, file_only=True)
        channel_list = self._rb_str_list(tool, "channels", channels)
        extra = self._rb_extra_args(tool, extra_args)
        with_args = self._rb_with_args(tool, specs)

        argv = [
            *with_args,
            "rattler-build",
            "test",
            "--package-file",
            package_file,
            "--log-style",
            "json",
        ]
        for channel in channel_list:
            argv.extend(["-c", channel])
        argv.extend(extra)
        return self._rb_dispatch("test", argv, wd, timeout, background, output_file)

    def rattler_build_result(self, job_id: str, context_lines: int = 20) -> dict[str, Any]:
        """Filtered summary of a finished rattler_build_build/rattler_build_test background job."""
        artifact = self.pixi_executor.read_job_artifact(job_id, RATTLER_BUILD_ARTIFACT)
        if artifact is None:
            raise ValueError(
                f"Job {job_id!r} is not a rattler_build_build/rattler_build_test background job"
            )
        status = self.pixi_executor.get_job_status(job_id, 1)
        state = status.get("status")
        if state == "running" or (state == "unknown" and status.get("retryable")):
            return {"state": "running", "job_id": job_id}
        if state != "completed":
            raise RuntimeError(status.get("error") or f"Job {job_id} is in state {state!r}")
        text = self.pixi_executor.read_job_output(job_id) or ""
        return {
            **summarize_build_log(text, status.get("exit_code"), context_lines=context_lines),
            "job_id": job_id,
            "command": artifact.get("command"),
            "output_file": status.get("output_file"),
            "execution_time": status.get("execution_time"),
        }

    def get_job_status(self, job_id: str, tail_lines: int = 50) -> dict[str, Any]:
        """Return the status and output tail of a background pixi task."""
        try:
            return self.pixi_executor.get_job_status(job_id, tail_lines)
        except Exception as e:
            return {
                "status": "unknown",
                "job_id": job_id,
                "error": f"Failed to get job status: {str(e)}",
            }

    def wait_for_job(
        self,
        job_id: str,
        wait_s: float = 15,
        result_contains: list[str] | None = None,
        max_result_lines: int = 25,
    ) -> dict[str, Any]:
        """Wait (bounded) for a background pixi task to finish; see pixi_wait."""
        try:
            return self.pixi_executor.wait_for_job(
                job_id, wait_s, result_contains, max_result_lines
            )
        except Exception as e:
            return {
                "job_id": job_id,
                "state": "error",
                "matched_lines": [],
                "error": f"Failed to wait for job: {str(e)}",
                "returned_because": "error",
            }

    def list_tasks(
        self,
        working_dir: str | None = None,
        environment: str | None = None,
        manifest_path: str | None = None,
    ) -> dict[str, Any]:
        """
        List all available pixi tasks with descriptions.

        Returns: {"tasks": {"test": "Run pytest", "lint": "Run ruff", ...}, "environment": ...}
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            # Same rule as run_task: manifest_path's parent holds the pixi project
            project_dir = str(Path(manifest_path).parent) if manifest_path else working_dir

            if not self.pixi_project.is_pixi_project(project_dir):
                return {
                    "tasks": {},
                    "environment": environment,
                    "error": f"Directory {project_dir} is not a pixi project",
                }

            available_tasks = self.pixi_project.get_available_tasks(
                project_dir, environment=environment
            )

            self.logging.log_info(
                "Listed pixi tasks",
                {
                    "task_count": len(available_tasks),
                    "working_dir": working_dir,
                    "environment": environment,
                },
            )

            return {"tasks": available_tasks, "environment": environment}

        except Exception as e:
            error_msg = f"Failed to list tasks: {str(e)}"
            self.logging.log_error(error_msg, {"working_dir": working_dir, "error": str(e)})

            return {"tasks": {}, "environment": environment, "error": error_msg}

    def task_exists(
        self,
        task_name: str,
        working_dir: str | None = None,
        environment: str | None = None,
    ) -> bool:
        """
        Check if a pixi task exists.

        Returns: True if task exists, False otherwise
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return False

            available_tasks = self.pixi_project.get_available_tasks(
                working_dir, environment=environment
            )
            return task_name in available_tasks

        except Exception as e:
            self.logging.log_error(
                f"Error checking task existence: {str(e)}",
                {"task_name": task_name, "working_dir": working_dir},
            )
            return False

    def install(
        self,
        working_dir: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        """
        Install/sync pixi environment and dependencies.

        Returns: {"success": bool, "stdout": str, "stderr": str, "execution_time": float, "environment": str | None}
        """
        start_time = time.time()
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Directory {working_dir} is not a pixi project",
                    "execution_time": time.time() - start_time,
                    "environment": environment,
                }

            context = PixiExecutionContext(
                working_dir=working_dir,
                timeout=600,  # Longer timeout for installations
                capture_output=True,
                environment=environment,
            )

            result = self.pixi_executor.install(context)

            self.logging.log_info(
                "Pixi install completed",
                {
                    "success": result.success,
                    "execution_time": result.execution_time,
                    "working_dir": working_dir,
                    "environment": environment,
                },
            )

            return {
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "execution_time": result.execution_time,
                "environment": environment,
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Pixi install failed: {str(e)}"

            self.logging.log_error(error_msg, {"working_dir": working_dir, "error": str(e)})

            return {
                "success": False,
                "stdout": "",
                "stderr": error_msg,
                "execution_time": execution_time,
                "environment": environment,
            }

    def get_info(self, working_dir: str | None = None) -> dict[str, Any]:
        """
        Get pixi project information and environment status.

        Returns: Project information including dependencies, tasks, environment status
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "is_pixi_project": False,
                    "error": f"Directory {working_dir} is not a pixi project",
                }

            project_info = self.pixi_project.get_project_info(working_dir)

            return {
                "is_pixi_project": True,
                "project_name": project_info.project_name,
                "project_path": project_info.project_path,
                "python_version": project_info.python_version,
                "environment_path": project_info.environment_path,
                "has_lock_file": project_info.has_lock_file,
                "dependencies": project_info.dependencies,
                "dev_dependencies": project_info.dev_dependencies,
                "available_tasks": project_info.available_tasks,
                "channels": project_info.channels,
                "platforms": project_info.platforms,
                "environment_status": project_info.environment_status,
                "last_updated": project_info.last_updated,
            }

        except Exception as e:
            error_msg = f"Failed to get project info: {str(e)}"
            self.logging.log_error(error_msg, {"working_dir": working_dir, "error": str(e)})

            return {"is_pixi_project": False, "error": error_msg}

    def execute_command(
        self,
        command: list[str],
        working_dir: str | None = None,
        capture_output: bool = True,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """
        Execute arbitrary command in pixi environment.

        Returns: Command execution result
        """
        start_time = time.time()
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Directory {working_dir} is not a pixi project",
                    "exit_code": 1,
                    "execution_time": time.time() - start_time,
                }

            context = PixiExecutionContext(
                working_dir=working_dir, timeout=timeout, capture_output=capture_output
            )

            result = self.pixi_executor.execute_command(command, context)

            self.logging.log_info(
                "Pixi command executed",
                {
                    "command": " ".join(command),
                    "success": result.success,
                    "execution_time": result.execution_time,
                    "working_dir": working_dir,
                },
            )

            return {
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "execution_time": result.execution_time,
                "command": " ".join(command),
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Command execution failed: {str(e)}"

            self.logging.log_error(
                error_msg,
                {"command": command, "working_dir": working_dir, "error": str(e)},
            )

            return {
                "success": False,
                "stdout": "",
                "stderr": error_msg,
                "exit_code": 1,
                "execution_time": execution_time,
                "command": " ".join(command),
            }

    def add_dependency(
        self,
        package: str,
        channel: str | None = None,
        is_dev: bool = False,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        """
        Add a dependency to pixi project.

        Returns: Operation result
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "success": False,
                    "message": f"Directory {working_dir} is not a pixi project",
                }

            result = self.pixi_project.add_dependency(package, channel, is_dev, working_dir)

            self.logging.log_info(
                "Dependency added",
                {
                    "package": package,
                    "channel": channel,
                    "is_dev": is_dev,
                    "success": result.success,
                    "working_dir": working_dir,
                },
            )

            return {
                "success": result.success,
                "message": result.message,
                "data": result.data,
            }

        except Exception as e:
            error_msg = f"Failed to add dependency: {str(e)}"
            self.logging.log_error(
                error_msg,
                {"package": package, "working_dir": working_dir, "error": str(e)},
            )

            return {"success": False, "message": error_msg}

    def remove_dependency(
        self, package: str, is_dev: bool = False, working_dir: str | None = None
    ) -> dict[str, Any]:
        """
        Remove a dependency from pixi project.

        Returns: Operation result
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "success": False,
                    "message": f"Directory {working_dir} is not a pixi project",
                }

            result = self.pixi_project.remove_dependency(package, is_dev, working_dir)

            self.logging.log_info(
                "Dependency removed",
                {
                    "package": package,
                    "is_dev": is_dev,
                    "success": result.success,
                    "working_dir": working_dir,
                },
            )

            return {
                "success": result.success,
                "message": result.message,
                "data": result.data,
            }

        except Exception as e:
            error_msg = f"Failed to remove dependency: {str(e)}"
            self.logging.log_error(
                error_msg,
                {"package": package, "working_dir": working_dir, "error": str(e)},
            )

            return {"success": False, "message": error_msg}

    def list_dependencies(self, working_dir: str | None = None) -> dict[str, Any]:
        """
        List all project dependencies with versions.

        Returns: Dependencies information
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            if not self.pixi_project.is_pixi_project(working_dir):
                return {
                    "dependencies": {},
                    "dev_dependencies": {},
                    "error": f"Directory {working_dir} is not a pixi project",
                }

            project_info = self.pixi_project.get_project_info(working_dir)

            return {
                "dependencies": project_info.dependencies,
                "dev_dependencies": project_info.dev_dependencies,
                "channels": project_info.channels,
                "platforms": project_info.platforms,
            }

        except Exception as e:
            error_msg = f"Failed to list dependencies: {str(e)}"
            self.logging.log_error(error_msg, {"working_dir": working_dir, "error": str(e)})

            return {"dependencies": {}, "dev_dependencies": {}, "error": error_msg}

    def get_project_status(self, working_dir: str | None = None) -> dict[str, Any]:
        """
        Get comprehensive project status.

        Returns: Project health and status information
        """
        working_dir = self._resolve_working_dir(working_dir)

        try:
            health_check = self.pixi_project.check_health(working_dir)

            return {
                "is_pixi_project": health_check.is_pixi_project,
                "pixi_executable_found": health_check.pixi_executable_found,
                "environment_exists": health_check.environment_exists,
                "environment_synced": health_check.environment_synced,
                "lock_file_exists": health_check.lock_file_exists,
                "is_healthy": health_check.is_healthy(),
                "issues": health_check.issues,
                "recommendations": health_check.recommendations,
                "checked_at": health_check.checked_at,
            }

        except Exception as e:
            error_msg = f"Failed to get project status: {str(e)}"
            self.logging.log_error(error_msg, {"working_dir": working_dir, "error": str(e)})

            return {
                "is_pixi_project": False,
                "is_healthy": False,
                "issues": [error_msg],
                "recommendations": ["Check if pixi is installed and directory contains pixi.toml"],
                "error": error_msg,
            }

    def init_project(self, path: str, template: str | None = None) -> dict[str, Any]:
        """
        Initialize a new pixi project.

        Returns: Initialization result
        """
        try:
            result = self.pixi_project.init_project(path, template)

            self.logging.log_info(
                "Pixi project initialized",
                {"path": path, "template": template, "success": result.success},
            )

            return {
                "success": result.success,
                "message": result.message,
                "project_path": path,
            }

        except Exception as e:
            error_msg = f"Failed to initialize project: {str(e)}"
            self.logging.log_error(error_msg, {"path": path, "template": template, "error": str(e)})

            return {"success": False, "message": error_msg, "project_path": path}
