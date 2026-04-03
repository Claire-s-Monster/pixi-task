#!/usr/bin/env python3
"""
Simple test to verify claudecode-shell server functionality.
"""

import sys
from pathlib import Path

# Add src to path
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

from core.container import Container
from core.models import FunctionExecutionRequest


def test_basic_functionality():
    """Test basic server functionality."""
    print("Testing ClaudeCode Shell MCP Server...")
    
    # Initialize container
    container = Container()
    service = container.shell_service
    
    # Test function validation
    print("\n1. Testing function validation...")
    validation = service.validate_function_exists("claudecode_system_info")
    print(f"   claudecode_system_info exists: {validation['exists']}")
    
    # Test function discovery
    print("\n2. Testing function discovery...")
    discovery = service.list_available_functions()
    print(f"   Found {discovery['total_count']} functions")
    print(f"   Categories: {list(discovery['categories'].keys())}")
    
    # Test system health
    print("\n3. Testing system health...")
    health = service.get_system_health()
    print(f"   System healthy: {health['healthy']}")
    print(f"   Available functions: {health['available_functions']}")
    
    # Test function execution (if claudecode_help exists)
    print("\n4. Testing function execution...")
    try:
        result = service.execute_function("claudecode_help")
        print(f"   claudecode_help execution: success={result['success']}")
        if result['success']:
            print(f"   Output length: {len(result['stdout'])} chars")
    except Exception as e:
        print(f"   claudecode_help not available: {e}")
    
    print("\n✅ Basic functionality test completed!")


if __name__ == "__main__":
    test_basic_functionality()