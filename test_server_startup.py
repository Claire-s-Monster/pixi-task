#!/usr/bin/env python3
"""
Test server startup and main function.
"""

import sys
sys.path.insert(0, 'src')

def test_server_main():
    """Test that server main function works."""
    print("🔍 Testing Pixi MCP Server Startup")
    print("=" * 50)
    
    try:
        from pixi_task.server import main, app
        print("✅ Server imports successful")
        
        print("Main function callable:", callable(main))
        print("App type:", type(app))
        print("App name:", getattr(app, 'name', 'unknown'))
        
        # Try to check if app can be run
        print("App has run method:", hasattr(app, 'run'))
        print("App has run_stdio_async method:", hasattr(app, 'run_stdio_async'))
        
        return True
        
    except Exception as e:
        print(f"❌ Server startup test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_server_script():
    """Check server script configuration."""
    print("\n📋 Checking Server Script Configuration")
    print("=" * 50)
    
    try:
        # Check pyproject.toml script configuration
        import toml
        with open('pyproject.toml', 'r') as f:
            config = toml.load(f)
        
        scripts = config.get('project', {}).get('scripts', {})
        print("Configured scripts:")
        for script_name, script_path in scripts.items():
            print(f"  {script_name}: {script_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Script configuration check failed: {e}")
        return False

if __name__ == "__main__":
    success1 = test_server_main()
    success2 = check_server_script()
    
    if success1 and success2:
        print("\n🎉 Server startup tests passed!")
        print("   Try running: pixi run pixi-task-server")
    else:
        print("\n❌ Server startup issues detected")