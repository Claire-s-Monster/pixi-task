"""Unit tests for core.rattler_build_log.summarize_build_log (issue #45).

Fixtures mirror rattler-build 0.76.1 ``--log-style json`` output captured from
probe recipes: one JSON object per line, followed by a plain-text miette
``Error:`` block on failure.
"""

from __future__ import annotations

import json

from core.rattler_build_log import (
    MAX_CONTEXT_LINES,
    MAX_ERROR_BLOCK_LINES,
    MAX_LINE_CHARS,
    MAX_WARNINGS,
    SUMMARY_CHAR_BUDGET,
    record_phase,
    summarize_build_log,
)

RECIPE = "probe-0.1.0-h4616a5c_0"
OUTER = {"recipe": RECIPE, "span_color": RECIPE, "name": "Running build for"}
TEST_OUTER = {
    "recipe": f"{RECIPE}.conda",
    "span_color": f"{RECIPE}.conda",
    "name": "Running script test for",
}
SCRIPT = "rattler_build_script::execution"


def rec(message, level="INFO", target="rattler_build", spans=None):
    obj = {
        "timestamp": "2026-10-15T14:22:41.729156Z",
        "level": level,
        "fields": {"message": message},
        "target": target,
    }
    if spans:
        obj["span"] = spans[-1]
        obj["spans"] = spans
    return json.dumps(obj)


def named(name):
    return {"name": name}


def anon(message):
    return {"message": message, "name": ""}


def build_rec(message, level="INFO"):
    return rec(message, level=level, target=SCRIPT, spans=[OUTER, named("Running build script")])


PREAMBLE = [
    rec("rattler-build 0.76.1"),
    rec("No configuration file loaded"),
    rec("Found 1 variants\n", spans=[named("Finding outputs from recipe")]),
    rec("Starting build of 1 outputs"),
    rec(
        "No sources to fetch",
        target="rattler_build_core::source",
        spans=[OUTER, named("Fetching source code")],
    ),
]

SOLVE_FAILURE = "\n".join(
    PREAMBLE
    + [
        rec(
            "  Specs:",
            target="rattler_build_core::render::solver",
            spans=[OUTER, anon("Resolving host environment")],
        ),
        rec(
            "   - definitely-not-a-real-package-xyz",
            target="rattler_build_core::render::solver",
            spans=[OUTER, anon("Resolving host environment")],
        ),
        "Error:   × Failed to resolve dependencies",
        "  ╰─▶ Cannot solve the request because of: No candidates were found for",
        "      definitely-not-a-real-package-xyz *.",
        "      ",
        "",
    ]
)

SOURCE_FAILURE = "\n".join(
    PREAMBLE[:4]
    + [
        rec(
            "Downloading from: https://example.invalid/nope-0.1.0.tar.gz",
            target="rattler_build_source_cache::cache",
            spans=[OUTER, named("Fetching source code")],
        ),
        rec(
            "Failed to fetch from https://example.invalid/nope-0.1.0.tar.gz:"
            " Failed to download from URL: Request failed after 3 retries",
            level="WARN",
            target="rattler_build_source_cache::cache",
            spans=[OUTER, named("Fetching source code")],
        ),
        "Error:   × Failed to download from URL: Request failed after 3 retries",
        "",
    ]
)

BUILD_FAILURE = "\n".join(
    PREAMBLE
    + [
        rec(
            "\nFinalized run dependencies: this output has no run dependencies",
            target="rattler_build_core::render::resolved_dependencies",
            spans=[OUTER],
        ),
        rec(
            "✔ Successfully updated the host environment",
            target="rattler_build_core::render::solver",
            spans=[OUTER, anon("Installing host environment")],
        ),
        build_rec("+ echo starting-build"),
        build_rec("starting-build"),
        build_rec("BUILD-ERROR-MARKER"),
        build_rec("+ exit 3"),
        build_rec("Script failed with status 3", level="ERROR"),
        build_rec(
            "\nScript execution failed.\n\n  Work directory: /work/out/bld/work\n", level="ERROR"
        ),
        "Error:   × Script failed to execute",
        "",
    ]
)

PACKAGING = [
    rec(
        "Compressing archive...",
        target="rattler_build_core::packaging",
        spans=[OUTER, named("Packaging new files")],
    ),
    rec(
        f"Archive written to '/work/out/noarch/{RECIPE}.conda'",
        target="rattler_build_core::packaging",
        spans=[OUTER, named("Packaging new files")],
    ),
    rec("Checking for symlinks ...", target="rattler_build_core::build", spans=[OUTER]),
    rec(
        "Collecting tests from '/tmp/.tmpUwxBm1/probe'",
        target="rattler_build_core::package_test::run_test",
    ),
    rec(
        "   - probe ==0.1.0 h4616a5c_0",
        target="rattler_build_core::render::solver",
        spans=[TEST_OUTER, anon("Resolving test environment")],
    ),
    rec(
        "✔ Successfully updated the test environment",
        target="rattler_build_core::render::solver",
        spans=[TEST_OUTER, anon("Installing test environment")],
    ),
    rec(
        "Testing commands:",
        target="rattler_build_core::package_test::run_test",
        spans=[TEST_OUTER],
    ),
]

TEST_FAILURE = "\n".join(
    PREAMBLE
    + PACKAGING
    + [
        rec("+ echo TEST-ERROR-MARKER", target=SCRIPT, spans=[TEST_OUTER]),
        rec("TEST-ERROR-MARKER", target=SCRIPT, spans=[TEST_OUTER]),
        rec("+ exit 7", target=SCRIPT, spans=[TEST_OUTER]),
        rec("Script failed with status 7", level="ERROR", target=SCRIPT, spans=[TEST_OUTER]),
        "Error:   × Test failed",
        "  ╰─▶ failed to run test: IO Error: Script failed with status 7",
        "      Script execution failed.",
        "      ",
        "        Work directory: /work/out/test/test_probe-",
        "      testJgAEJ7/test",
        "",
    ]
)

SUCCESS = "\n".join(
    PREAMBLE
    + PACKAGING
    + [
        rec("+ test -f $PREFIX/share/probe.txt", target=SCRIPT, spans=[TEST_OUTER]),
        rec("✔ all tests passed!", target="rattler_build_core::package_test::run_test"),
        rec(
            f"Artifact: /work/out/noarch/{RECIPE}.conda (1.86 KiB)",
            target="rattler_build_core::types::build_output",
            spans=[named("Build summary"), {"recipe": RECIPE, "name": "Build summary for"}],
        ),
        "",
    ]
)


# --- phase detection -------------------------------------------------------


def phase_of(line):
    return record_phase(json.loads(line))


def test_record_phase_uses_innermost_meaningful_span():
    assert phase_of(PREAMBLE[2]) == "render"
    assert phase_of(PREAMBLE[4]) == "source"
    # The outer "Running build for" span alone carries no phase.
    assert phase_of(rec("x", spans=[OUTER])) is None
    assert phase_of(rec("x")) is None


def test_record_phase_anonymous_spans():
    def phase(msg):
        return phase_of(rec("x", spans=[OUTER, anon(msg)]))

    assert phase("Resolving host environment") == "solve"
    assert phase("Resolving build environment") == "solve"
    assert phase("Installing host environment") == "install"
    assert phase("Resolving test environment") == "test"
    assert phase("Installing test environment") == "test"


def test_record_phase_build_package_test():
    assert phase_of(build_rec("x")) == "build"
    assert phase_of(rec("x", spans=[OUTER, named("Packaging new files")])) == "package"
    assert phase_of(rec("x", spans=[TEST_OUTER])) == "test"
    assert phase_of(rec("x", target="rattler_build_core::package_test::run_test")) == "test"


# --- acceptance: solve failure ---------------------------------------------


def test_solve_failure_reports_solve_phase_and_no_candidates_line():
    out = summarize_build_log(SOLVE_FAILURE, exit_code=1)
    assert out["status"] == "failed"
    assert out["phase"] == "solve"
    assert out["error"].startswith("Failed to resolve dependencies")
    assert "No candidates were found" in out["error"]
    assert "definitely-not-a-real-package-xyz" in out["error"]
    assert any("No candidates were found" in line for line in out["error_block"].splitlines())
    # With no ERROR record, context is the tail of the last (solve) phase.
    assert "   - definitely-not-a-real-package-xyz" in out["context"].splitlines()
    assert out["error_count"] == 0


# --- other failure phases --------------------------------------------------


def test_source_failure():
    out = summarize_build_log(SOURCE_FAILURE, exit_code=1)
    assert out["phase"] == "source"
    assert out["error"] == "Failed to download from URL: Request failed after 3 retries"
    assert out["warning_count"] == 1
    assert out["warnings"][0].startswith("Failed to fetch from https://example.invalid")


def test_build_failure_takes_first_error_and_script_context():
    out = summarize_build_log(BUILD_FAILURE, exit_code=1)
    assert out["status"] == "failed"
    assert out["phase"] == "build"
    assert out["error"] == "Script failed with status 3"
    assert out["error_count"] == 2
    # Only the failing phase's lines, oldest first.
    assert out["context"].splitlines() == [
        "+ echo starting-build",
        "starting-build",
        "BUILD-ERROR-MARKER",
        "+ exit 3",
    ]
    assert out["error_block"].startswith("Error:   × Script failed to execute")


def test_test_failure():
    out = summarize_build_log(TEST_FAILURE, exit_code=1)
    assert out["phase"] == "test"
    assert out["error"] == "Script failed with status 7"
    ctx = out["context"].splitlines()
    assert "TEST-ERROR-MARKER" in ctx
    assert "Testing commands:" in ctx
    # The package was written before its test failed.
    assert out["packages"] == [f"/work/out/noarch/{RECIPE}.conda"]


def test_error_headline_unwraps_miette_cause():
    out = summarize_build_log(TEST_FAILURE, exit_code=1)
    assert out["error_headline"] == (
        "Test failed: failed to run test: IO Error: Script failed with status 7"
        " Script execution failed."
    )


def test_multiline_error_message_flattened():
    text = build_rec("\nScript execution failed.\n\n  Work directory: /w", level="ERROR")
    out = summarize_build_log(text, exit_code=1)
    assert out["error"] == "Script execution failed. Work directory: /w"


# --- success / status --------------------------------------------------------


def test_success():
    out = summarize_build_log(SUCCESS, exit_code=0)
    assert out["status"] == "success"
    assert out["phase"] is None
    assert out["error"] is None
    assert out["error_block"] == ""
    assert out["context"] == ""
    assert out["packages"] == [f"/work/out/noarch/{RECIPE}.conda"]
    assert out["tests_passed"] == 1
    assert out["truncated"] is False


def test_status_without_exit_code():
    assert summarize_build_log(SOLVE_FAILURE)["status"] == "failed"
    assert summarize_build_log(SUCCESS)["status"] == "unknown"


def test_nonzero_exit_without_any_error_output():
    out = summarize_build_log("\n".join(PREAMBLE), exit_code=137)
    assert out["status"] == "failed"
    assert out["phase"] == "source"
    assert out["error"] is None


def test_empty_log():
    out = summarize_build_log("", exit_code=None)
    assert out["status"] == "unknown"
    assert out["phase"] is None
    assert out["packages"] == []


# --- robustness --------------------------------------------------------------


def test_ansi_and_non_json_noise_ignored_before_error_block():
    text = "\n".join(
        [
            "\x1b[33mWARN some pixi chatter\x1b[0m",
            "not json {",
            PREAMBLE[2],
            "\x1b[31mError:   × Boom\x1b[0m",
        ]
    )
    out = summarize_build_log(text, exit_code=1)
    assert out["phase"] == "render"
    assert out["error"] == "Boom"
    assert "\x1b" not in out["error_block"]


PATCH_RECIPE = "probe-patch-bad-0.1.0-h4616a5c_0"
PATCH_OUTER = {"recipe": PATCH_RECIPE, "span_color": PATCH_RECIPE, "name": "Running build for"}
PATCH_SPANS = [PATCH_OUTER, named("Fetching source code")]
PATCH_PREAMBLE = PREAMBLE[:4]
PATCH_SOURCE_LINES = [
    rec(
        "Fetching source from path: /tmp/src",
        target="rattler_build_core::source",
        spans=PATCH_SPANS,
    ),
    rec(
        "Copied 1 files into isolated environment",
        target="rattler_build_core::source",
        spans=PATCH_SPANS,
    ),
]
PATCH_LINE = rec(
    "Applying patch: /tmp/bad.patch",
    target="rattler_build_core::source::patch",
    spans=PATCH_SPANS,
)
PATCH_ERROR_BLOCK = [
    "Error:   × Patch application error: error applying hunk #1: could not find context in",
    "  │ target file",
    "  │ ",
    "  │ Hunk content:",
    "  │ @@ -1,3 +1,3 @@",
    "  │  line one",
    "  │ -line 2",
    "  │ +line TWO",
    "  │  line three",
    "  │ ",
    "  ╰─▶ error applying hunk #1: could not find context in target file",
    "      ",
    "      Hunk content:",
    "      @@ -1,3 +1,3 @@",
    "       line one",
    "      -line 2",
    "      +line TWO",
    "       line three",
    "      ",
    "",
]
PATCH_FAILURE = "\n".join(PATCH_PREAMBLE + PATCH_SOURCE_LINES + [PATCH_LINE] + PATCH_ERROR_BLOCK)
PATCH_HEADLINE = (
    "Patch application error: error applying hunk #1: could not find context in target file"
)

PATCH_OK_BUILD_FAILURE = "\n".join(
    PATCH_PREAMBLE
    + PATCH_SOURCE_LINES
    + [
        PATCH_LINE,
        rec(
            "\nFinalized run dependencies: this output has no run dependencies",
            target="rattler_build_core::render::resolved_dependencies",
            spans=[PATCH_OUTER],
        ),
        rec(
            "Installing build environment",
            target="rattler_build_core::render::solver",
            spans=[PATCH_OUTER, anon("Installing build environment")],
        ),
        rec(
            "Installing host environment",
            target="rattler_build_core::render::solver",
            spans=[PATCH_OUTER, anon("Installing host environment")],
        ),
        rec(
            "line TWO",
            target=SCRIPT,
            spans=[PATCH_OUTER, named("Running build script")],
        ),
        rec(
            "+ exit 3",
            target=SCRIPT,
            spans=[PATCH_OUTER, named("Running build script")],
        ),
        rec(
            "Script failed with status 3",
            level="ERROR",
            target=SCRIPT,
            spans=[PATCH_OUTER, named("Running build script")],
        ),
        "Error:   × Script failed to execute",
        "",
    ]
)


def test_failed_patch_is_reported_as_patch_with_joined_headline():
    out = summarize_build_log(PATCH_FAILURE, exit_code=1)
    assert out["status"] == "failed"
    assert out["phase"] == "patch"
    assert out["error"] == PATCH_HEADLINE
    assert out["error_count"] == 0
    assert "Applying patch:" in out["context"]


def test_build_failure_after_successful_patch_is_reported_as_build():
    out = summarize_build_log(PATCH_OK_BUILD_FAILURE, exit_code=1)
    assert out["phase"] == "build"
    assert out["error"] == "Script failed with status 3"


def test_patch_in_recipe_name_does_not_make_source_failure_a_patch_failure():
    spans = [
        {"recipe": "probe-patch-x", "span_color": "probe-patch-x", "name": "Running build for"},
        named("Fetching source code"),
    ]
    text = "\n".join(
        PATCH_PREAMBLE
        + [
            rec("Downloading from: https://example.invalid/x.tar.gz", spans=spans),
            "Error:   × Failed to download from URL: Request failed after 3 retries",
        ]
    )
    assert summarize_build_log(text, exit_code=1)["phase"] == "source"


def test_record_phase_of_patch_target_is_patch():
    assert record_phase(json.loads(PATCH_LINE)) == "patch"


# --- caps and budget ---------------------------------------------------------


def test_context_capped_to_failing_phase_tail():
    lines = PREAMBLE + [build_rec(f"line {i}") for i in range(200)]
    lines.append(build_rec("Script failed", level="ERROR"))
    ctx = summarize_build_log("\n".join(lines), exit_code=1)["context"].splitlines()
    assert len(ctx) == MAX_CONTEXT_LINES
    assert ctx[-1] == "line 199"


def test_context_lines_parameter():
    out = summarize_build_log(BUILD_FAILURE, exit_code=1, context_lines=2)
    assert out["context"].splitlines() == ["BUILD-ERROR-MARKER", "+ exit 3"]


def test_error_block_line_count_capped():
    text = "\n".join(
        ["Error:   × Huge"] + [f"  line {i}" for i in range(MAX_ERROR_BLOCK_LINES * 2)]
    )
    block = summarize_build_log(text, exit_code=1)["error_block"].splitlines()
    assert len(block) == MAX_ERROR_BLOCK_LINES + 1
    assert block[-1].startswith("... (")


def test_long_lines_clipped():
    text = "\n".join(["Error:   × Huge"] + ["y" * (MAX_LINE_CHARS * 3)] * 3)
    block = summarize_build_log(text, exit_code=1)["error_block"].splitlines()
    assert all(len(line) <= MAX_LINE_CHARS + 3 for line in block)


def test_warnings_capped_but_counted():
    lines = PREAMBLE + [rec(f"warn {i}", level="WARN") for i in range(MAX_WARNINGS + 5)]
    out = summarize_build_log("\n".join(lines), exit_code=0)
    assert out["warning_count"] == MAX_WARNINGS + 5
    assert len(out["warnings"]) == MAX_WARNINGS


def test_summary_fits_budget_on_pathological_log():
    big = "z" * (MAX_LINE_CHARS * 2)
    lines = PREAMBLE + [rec(f"{i} {big}", level="WARN") for i in range(MAX_WARNINGS)]
    lines += [build_rec(f"{i} {big}") for i in range(100)]
    lines.append(build_rec("Script failed with status 2", level="ERROR"))
    lines += ["Error:   × Script failed to execute"] + [f"  {i} {big}" for i in range(100)]
    out = summarize_build_log("\n".join(lines), exit_code=1)
    assert len(json.dumps(out, indent=2)) <= SUMMARY_CHAR_BUDGET
    assert out["truncated"] is True
    assert out["phase"] == "build"
    assert out["error"] == "Script failed with status 2"
    assert out["context"].splitlines()[-1].startswith("99 ")
