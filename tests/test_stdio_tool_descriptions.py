"""Issue #45 acceptance: meta-tool descriptions (stdio, all complexities) name only registered tools."""

from __future__ import annotations

import inspect
import re
from unittest.mock import MagicMock

from pixi_task.lean_mcp_interface import LeanMCPInterface

TOOL_NAME_PATTERN = re.compile(r"\b(?:pixi|rattler|conda)_[a-z0-9_]+\b")
META_TOOLS = ("discover_tools", "get_tool_spec", "execute_tool")


async def test_meta_tool_text_only_names_registered_tools():
    iface = LeanMCPInterface(MagicMock())
    registered = set(iface.tool_registry)

    texts: list[str] = []
    for tool in await iface.app.list_tools():
        if tool.name in META_TOOLS:
            texts.append(tool.description or "")
            texts.append(inspect.getdoc(tool.fn) or "")
    assert len(texts) == 2 * len(META_TOOLS)

    mentioned = {token for text in texts for token in TOOL_NAME_PATTERN.findall(text)}
    assert mentioned, "expected the meta-tool text to mention at least one tool"
    offenders = sorted(mentioned - registered)
    assert not offenders, f"meta-tool descriptions name unregistered tools: {offenders}"


def test_get_tool_spec_not_found_hint_lists_only_registered_tools():
    iface = LeanMCPInterface(MagicMock())
    hint = iface.dispatch_meta_tool("get_tool_spec", {"tool_name": "rattler_build_smart_typo"})
    assert hint["error"].startswith("Tool 'rattler_build_smart_typo' not found")
    assert set(hint["available_tools"]) == set(iface.tool_registry)
