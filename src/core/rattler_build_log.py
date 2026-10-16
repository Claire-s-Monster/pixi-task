"""Pure helpers that condense rattler-build logs for the rattler-build tools (issue #45).

Input is ``rattler-build --log-style json`` output: one JSON object per line
(``level``, ``fields.message``, ``target``, ``span``, ``spans``), followed on
failure by a plain-text miette ``Error:`` block that is not JSON.
"""

from __future__ import annotations

import json
import re
from collections import deque
from typing import Any

MAX_CONTEXT_LINES = 20
MAX_ERROR_BLOCK_LINES = 40
MAX_LINE_CHARS = 240
MAX_HEADLINE_CHARS = 500
MAX_WARNINGS = 10
MAX_PACKAGES = 20
# apply_token_limits rewrites any response over ~8000 chars (strings cut to
# 400 chars, later keys dropped), so the summary trims itself below that.
SUMMARY_CHAR_BUDGET = 6000
# Budget trimming never cuts context or the error block below this many lines
# until warnings are gone.
MIN_KEPT_LINES = 5

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_ARCHIVE = re.compile(r"^Archive written to '(.+)'$")
_PATCH_WORD = re.compile(r"(?i)\bpatch\b")
_MIETTE_BAR = re.compile(r"^\s*│")
_MIETTE_CAUSE = re.compile(r"^\s*[╰├]─+▶\s*")

_SPAN_PHASES = {
    "Finding outputs from recipe": "render",
    "Fetching source code": "source",
    "Running build script": "build",
    "Packaging new files": "package",
}


def _span_phase(span: dict[str, Any]) -> str | None:
    label = span.get("name") or span.get("message") or ""
    if label in _SPAN_PHASES:
        return _SPAN_PHASES[label]
    low = label.lower()
    # Covers "Running script test for" and "Resolving/Installing test environment".
    if "test" in low:
        return "test"
    if low.startswith("resolving"):
        return "solve"
    if low.startswith("installing"):
        return "install"
    if "patch" in low:
        return "patch"
    return None


def record_phase(record: dict[str, Any]) -> str | None:
    """Build phase of one JSON log record, from its innermost meaningful span.

    The outer "Running build for" span carries no phase, so records that only
    have it return None and the caller keeps the previous phase. Patch records
    are logged inside the "Fetching source code" span, so the target wins.
    """
    if str(record.get("target", "")).startswith("rattler_build_core::source::patch"):
        return "patch"
    spans = record.get("spans") or ([record["span"]] if record.get("span") else [])
    for span in reversed(spans):
        if isinstance(span, dict) and (phase := _span_phase(span)):
            return phase
    if str(record.get("target", "")).startswith("rattler_build_core::package_test"):
        return "test"
    return None


def _parse_record(line: str) -> dict[str, Any] | None:
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _clip(line: str, limit: int = MAX_LINE_CHARS) -> str:
    return line if len(line) <= limit else line[:limit] + "..."


def _flatten(message: str) -> str:
    """One whitespace-collapsed line, clipped."""
    return _clip(" ".join(message.split()))


def _headline(block: list[str]) -> str | None:
    """``<title>: <cause>`` from a miette block, with hard-wrapped cause lines joined."""
    if not block:
        return None
    title = [block[0].removeprefix("Error:").strip().lstrip("×").strip()]
    rest = block[1:]
    # miette wraps a long title onto "│ ..." lines that end at a bare "│".
    while rest and (bar := _MIETTE_BAR.match(rest[0])) and rest[0][bar.end() :].strip():
        title.append(rest.pop(0)[bar.end() :].strip())
    while rest and _MIETTE_BAR.match(rest[0]):
        rest.pop(0)
    head = " ".join(title)
    cause: list[str] = []
    for line in rest:
        marker = _MIETTE_CAUSE.match(line)
        if not cause:
            if not marker:
                break
            cause.append(line[marker.end() :].strip())
        elif marker or not line.strip():
            break
        else:
            cause.append(line.strip())
    joined = " ".join(cause)
    if joined and joined not in head:
        head = f"{head}: {joined}"
    return _clip(head, MAX_HEADLINE_CHARS)


def _cap_block(block: list[str]) -> list[str]:
    while block and not block[-1].strip():
        block.pop()
    lines = [_clip(line) for line in block[:MAX_ERROR_BLOCK_LINES]]
    if len(block) > MAX_ERROR_BLOCK_LINES:
        lines.append(f"... ({len(block) - MAX_ERROR_BLOCK_LINES} more lines in output_file)")
    return lines


def _fit_budget(
    summary: dict[str, Any], context: list[str], block: list[str], warnings: list[str]
) -> None:
    """Fill the text fields, dropping oldest context, then block tail, then warnings."""
    while True:
        summary["context"] = "\n".join(context)
        summary["error_block"] = "\n".join(block)
        summary["warnings"] = warnings
        if len(json.dumps(summary, indent=2)) <= SUMMARY_CHAR_BUDGET:
            return
        if len(context) > MIN_KEPT_LINES:
            context.pop(0)
        elif len(block) > MIN_KEPT_LINES:
            block.pop()
        elif warnings:
            warnings.pop()
        elif context:
            context.pop(0)
        elif block:
            block.pop()
        else:
            return
        summary["truncated"] = True


def summarize_build_log(
    text: str, exit_code: int | None = None, *, context_lines: int = MAX_CONTEXT_LINES
) -> dict[str, Any]:
    """Condense a ``--log-style json`` rattler-build log into a small summary.

    ``phase`` is the phase of the first ERROR record or, when rattler-build
    emits none (solve failures), the last phase seen before the Error block.
    ``context`` holds the last ``context_lines`` INFO lines of that phase.
    """
    phase: str | None = None
    error: str | None = None
    error_phase: str | None = None
    error_count = 0
    context: list[str] = []
    recent: deque[tuple[str | None, str]] = deque(maxlen=max(context_lines, 0))
    warnings: list[str] = []
    warning_count = 0
    packages: list[str] = []
    tests_passed = 0
    block: list[str] = []

    for raw in text.splitlines():
        line = _ANSI.sub("", raw).rstrip()
        if block:
            block.append(line)
            continue
        record = _parse_record(line)
        if record is None:
            if line.startswith("Error:"):
                block.append(line)
            continue

        fields = record.get("fields")
        message = str(fields.get("message") or "") if isinstance(fields, dict) else ""
        span_phase = record_phase(record)
        # Patches are applied inside the source span; keep "patch" once seen.
        if span_phase is not None and not (span_phase == "source" and phase == "patch"):
            phase = span_phase

        level = record.get("level")
        if level == "ERROR":
            error_count += 1
            if error is None:
                error = _flatten(message)
                error_phase = phase
                context = [msg for ph, msg in recent if ph == phase]
        elif level == "WARN":
            warning_count += 1
            if len(warnings) < MAX_WARNINGS:
                warnings.append(_flatten(message))
        else:
            archive = _ARCHIVE.match(message.strip())
            if archive and len(packages) < MAX_PACKAGES:
                packages.append(archive.group(1))
            if message.startswith("✔ all tests passed"):
                tests_passed += 1
            if error is None:
                for sub in message.splitlines():
                    if sub.strip():
                        recent.append((phase, _clip(sub.rstrip())))

    headline = _headline(block)
    if exit_code == 0:
        status = "success"
    elif exit_code is not None or error is not None or block:
        status = "failed"
    else:
        status = "unknown"

    failed_phase: str | None = None
    if status == "failed":
        if error is not None:
            failed_phase = error_phase
        else:
            failed_phase = phase
            context = [msg for ph, msg in recent if ph == phase]
        if failed_phase == "source" and headline and _PATCH_WORD.search(headline):
            failed_phase = "patch"

    summary: dict[str, Any] = {
        "status": status,
        "exit_code": exit_code,
        "phase": failed_phase,
        "error": error if error is not None else headline,
        "error_headline": headline,
        "error_count": error_count,
        "warning_count": warning_count,
        "packages": packages,
        "tests_passed": tests_passed,
        "truncated": False,
    }
    _fit_budget(summary, context, _cap_block(block), warnings)
    return summary
