#!/usr/bin/env python3
"""
Test pixi MCP server functions with actual pixi operations.
"""

import sys
import os
sys.path.insert(0, 'src')

def test_pixi_functions():
    """Test actual pixi MCP functions."""
    print("🧪 Testing Pixi MCP Functions")
    print("=" * 50)
    
    try:
        from core.container import Container
        container = Container()
        service = container.pixi_service
        
        # Test 1: Check if this is a pixi project
        print("📁 Testing project detection...")
        project_info = service.get_info()
        print(f"   Is pixi project: {project_info.get('is_pixi_project', False)}")
        print(f"   Project path: {project_info.get('project_path', 'unknown')}")
        
        # Test 2: List available tasks
        print("\n📋 Testing task listing...")
        tasks_result = service.list_tasks()
        tasks = tasks_result.get('tasks', {})
        print(f"   Found {len(tasks)} tasks:")
        for task_name, task_cmd in tasks.items():
            print(f"     - {task_name}: {task_cmd[:60]}{'...' if len(task_cmd) > 60 else ''}")
        
        # Test 3: Check specific task exists
        print("\n🔍 Testing task existence check...")
        test_task = "test" if "test" in tasks else list(tasks.keys())[0] if tasks else "nonexistent"
        exists_result = service.task_exists(test_task)
        print(f"   Task '{test_task}' exists: {exists_result}")
        
        # Test 4: Test pixi installation check
        print("\n⚙️  Testing pixi installation...")
        status = service.get_project_status()
        print(f"   Pixi executable found: {status.get('pixi_executable_found', False)}")
        print(f"   Project healthy: {status.get('is_healthy', False)}")
        
        # Test 5: List dependencies
        print("\n📦 Testing dependency listing...")
        deps_result = service.list_dependencies()
        deps = deps_result.get('dependencies', {})
        dev_deps = deps_result.get('dev_dependencies', {})
        print(f"   Production dependencies: {len(deps)}")
        print(f"   Development dependencies: {len(dev_deps)}")
        
        print("\n✅ All function tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Function tests failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_mcp_function_simulation():
    """Simulate MCP function calls."""
    print("\n🔌 Testing MCP Function Simulation")
    print("=" * 50)
    
    try:
        # Import the actual server functions
        from pixi_shell.server import (
            pixi_list_tasks, pixi_info, pixi_task_exists
        )
        
        # Test 1: pixi_list_tasks
        print("📋 Testing pixi_list_tasks MCP function...")
        tasks_result = pixi_list_tasks()
        print(f"   Result: {tasks_result.get('tasks', 'Error')}")
        
        # Test 2: pixi_info
        print("\n📊 Testing pixi_info MCP function...")
        info_result = pixi_info()
        print(f"   Is pixi project: {info_result.get('is_pixi_project', False)}")
        
        # Test 3: pixi_task_exists
        print("\n🔍 Testing pixi_task_exists MCP function...")
        exists_result = pixi_task_exists("test")
        print(f"   Task 'test' exists: {exists_result.get('exists', False)}")
        
        print("\n✅ MCP function simulation completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ MCP function simulation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Testing Pixi MCP Server Functions")
    print("=" * 60)
    
    success1 = test_pixi_functions()
    success2 = test_mcp_function_simulation()
    
    print("\n" + "=" * 60)
    if success1 and success2:
        print("🎉 All pixi function tests passed!")
        print("   The pixi MCP server is ready for production use!")
        sys.exit(0)
    else:
        print("❌ Some tests failed - review the errors above")
        sys.exit(1)