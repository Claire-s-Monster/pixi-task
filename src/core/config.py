"""Server-side configuration for pixi_exec (issue #43).

Only this server's *own* ``pyproject.toml`` is read: a target repository must
never be able to extend the set of tools the server will run.
"""

import re
import tomllib
from pathlib import Path

DEFAULT_EXEC_ALLOWLIST = ("rattler-build", "conda-smithy", "grayskull", "conda-forge-linter")

_TOOL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def server_pyproject_path() -> Path:
    """Path to the pixi-task server's own pyproject.toml."""
    return Path(__file__).resolve().parents[2] / "pyproject.toml"


def load_exec_allowlist(pyproject_path: Path | None = None) -> frozenset[str]:
    """Load the pixi_exec allowlist from ``[tool.pixi-task].exec_allowlist``.

    A missing file, table or key yields DEFAULT_EXEC_ALLOWLIST. A present key
    must be a list of plain tool names (an empty list allows nothing).
    """
    path = pyproject_path or server_pyproject_path()
    if not path.is_file():
        return frozenset(DEFAULT_EXEC_ALLOWLIST)

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    table = data.get("tool", {}).get("pixi-task", {})
    if "exec_allowlist" not in table:
        return frozenset(DEFAULT_EXEC_ALLOWLIST)

    value = table["exec_allowlist"]
    if not isinstance(value, list):
        raise ValueError(f"[tool.pixi-task].exec_allowlist must be a list, got {value!r}")
    for entry in value:
        if not isinstance(entry, str) or not _TOOL_NAME.fullmatch(entry):
            raise ValueError(f"Invalid exec_allowlist entry: {entry!r}")
    return frozenset(value)
