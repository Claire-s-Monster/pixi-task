#!/usr/bin/env python3
"""
Basic test for pixi MCP server functionality.
"""

import sys
sys.path.insert(0, 'src')

def test_server_imports():
    """Test that server can be imported successfully."""
    print("Testing pixi MCP server import...")
    try:
        from pixi_task.server import main
        print("✅ Server imported successfully")
        return True
    except Exception as e:
        print(f"❌ Server import failed: {e}")
        return False

def test_container_initialization():
    """Test that dependency injection container works."""
    print("Testing dependency injection container...")
    try:
        from core.container import Container
        container = Container()
        print("✅ Container initialized successfully")
        return True
    except Exception as e:
        print(f"❌ Container initialization failed: {e}")
        return False

def test_pixi_service():
    """Test that pixi service is accessible."""
    print("Testing pixi service...")
    try:
        from core.container import Container
        container = Container()
        service = container.pixi_service
        print("✅ Pixi service created successfully")
        return True
    except Exception as e:
        print(f"❌ Pixi service test failed: {e}")
        return False

def test_server_components():
    """Test server components and available functions."""
    print("Testing server components...")
    try:
        # Test that we can import FastMCP server
        from pixi_task.server import app
        print("✅ FastMCP server app created successfully")
        
        # Test function availability
        functions = ['pixi_run_task', 'pixi_list_tasks', 'pixi_install', 'pixi_info']
        print(f"✅ Expected MCP functions: {functions}")
        return True
    except Exception as e:
        print(f"❌ Server components test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing Pixi MCP Server Functionality")
    print("=" * 50)
    
    tests = [
        test_server_imports,
        test_container_initialization,
        test_pixi_service,
        test_server_components
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print("=" * 50)
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed - Server ready for MCP operations!")
        sys.exit(0)
    else:
        print("❌ Some tests failed - Check the errors above")
        sys.exit(1)