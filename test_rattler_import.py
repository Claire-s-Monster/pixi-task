#!/usr/bin/env python3
"""Quick test for rattler_build_smart implementation."""
import sys
sys.path.insert(0, "src")

from core.pixi_service import PixiShellService
print("✓ Service import OK")

from pixi_task.lean_mcp_interface import LeanMCPInterface
print("✓ Interface import OK")

# Check the method exists
assert hasattr(PixiShellService, "rattler_build_smart"), "Method not found!"
print("✓ rattler_build_smart method exists")

# Check tool registry will include it
from core.container import Container
container = Container()
interface = LeanMCPInterface(container)

# Verify tool is registered
assert "rattler_build_smart" in interface.tool_registry
print("✓ Tool registered in registry")

# Get tool spec
spec = interface.tool_registry["rattler_build_smart"]
print(f"✓ Tool spec: domain={spec['domain']}, complexity={spec['complexity']}")
print(f"  Description: {spec['description']}")

print("\n✅ All checks passed!")
