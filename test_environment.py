#!/usr/bin/env python3
"""
Test script to check what environment the claudecode-shell server sees.
"""

import os
import sys
from pathlib import Path

# Add src to path
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

from core.container import Container


def test_environment():
    """Test what environment variables the server can see."""
    print("=== Environment Check for ClaudeCode Shell MCP Server ===\n")
    
    # Check current environment
    print("1. Environment Variables:")
    print(f"   BASH_ENV: {os.environ.get('BASH_ENV', 'NOT SET')}")
    print(f"   CLAUDECODE_PATH: {os.environ.get('CLAUDECODE_PATH', 'NOT SET')}")
    print(f"   PATH: {os.environ.get('PATH', 'NOT SET')[:200]}...")
    print(f"   PWD: {os.environ.get('PWD', 'NOT SET')}")
    print(f"   USER: {os.environ.get('USER', 'NOT SET')}")
    print()
    
    # Initialize container and test environment adapter
    container = Container()
    env_adapter = container.environment
    
    print("2. Environment Adapter Discovery:")
    print(f"   Working Directory: {env_adapter.get_working_directory()}")
    print(f"   ClaudeCode Paths: {env_adapter.claudecode_paths}")
    print()
    
    # Test function discovery using environment
    print("3. Function Path Discovery:")
    test_functions = [
        "claudecode_help",
        "claudecode_system_info", 
        "claudecode_version",
        "claudecode_git_status",
        "claudecode_pixi_compliance"
    ]
    
    for func_name in test_functions:
        path = env_adapter.get_function_path(func_name)
        exists = env_adapter.check_function_exists(func_name)
        print(f"   {func_name}: path={path}, exists={exists}")
    
    print()
    
    # Test service discovery
    service = container.shell_service
    print("4. Service Function Discovery:")
    discovery = service.list_available_functions()
    print(f"   Total functions found: {discovery['total_count']}")
    print(f"   Categories: {list(discovery['categories'].keys())}")
    
    # Show first few functions that actually exist
    existing_functions = [f for f in discovery['functions'] if f['exists']]
    print(f"   Functions that exist: {len(existing_functions)}")
    if existing_functions:
        print("   First 5 existing functions:")
        for func in existing_functions[:5]:
            print(f"     - {func['name']}: {func['path']}")
    
    print()
    print("5. Test Function Execution:")
    if existing_functions:
        test_func = existing_functions[0]['name']
        print(f"   Testing execution of: {test_func}")
        result = service.execute_function(test_func, [])
        print(f"   Result: success={result['success']}, exit_code={result['exit_code']}")
        if not result['success']:
            print(f"   Error: {result['stderr']}")
    else:
        print("   No existing functions found to test")


if __name__ == "__main__":
    test_environment()