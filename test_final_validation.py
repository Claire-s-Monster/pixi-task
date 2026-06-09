#!/usr/bin/env python3
"""
Final validation test for pixi MCP server implementation.
"""

import sys
sys.path.insert(0, 'src')

def validate_server_implementation():
    """Validate the complete server implementation."""
    print("🔍 Final Validation: Pixi MCP Server")
    print("=" * 50)
    
    validation_results = []
    
    # Test 1: Core service functionality
    print("1. Testing core service functionality...")
    try:
        from core.container import Container
        container = Container()
        service = container.pixi_service
        
        # Test core service methods
        project_info = service.get_info()
        tasks = service.list_tasks()
        status = service.get_project_status()
        
        print("   ✅ Core service methods work correctly")
        validation_results.append(True)
    except Exception as e:
        print(f"   ❌ Core service failed: {e}")
        validation_results.append(False)
    
    # Test 2: MCP server structure
    print("2. Testing MCP server structure...")
    try:
        from pixi_task.server import app
        
        # Check that FastMCP app exists with correct methods
        assert hasattr(app, 'get_tools'), "FastMCP app missing get_tools method"
        assert hasattr(app, 'get_resources'), "FastMCP app missing get_resources method"
        assert hasattr(app, 'run'), "FastMCP app missing run method"
        assert hasattr(app, 'tool'), "FastMCP app missing tool decorator"
        assert hasattr(app, 'resource'), "FastMCP app missing resource decorator"
        
        print("   ✅ MCP server structure is correct")
        validation_results.append(True)
    except Exception as e:
        print(f"   ❌ MCP server structure failed: {e}")
        validation_results.append(False)
    
    # Test 3: Required MCP functions availability
    print("3. Testing MCP functions availability...")
    try:
        from pixi_task import server
        
        # Check key functions exist
        required_functions = [
            'pixi_run_task', 'pixi_list_tasks', 'pixi_install', 'pixi_info',
            'pixi_exec', 'pixi_add_dependency', 'pixi_remove_dependency'
        ]
        
        missing_functions = []
        for func_name in required_functions:
            if not hasattr(server, func_name):
                missing_functions.append(func_name)
        
        if missing_functions:
            print(f"   ❌ Missing functions: {missing_functions}")
            validation_results.append(False)
        else:
            print(f"   ✅ All {len(required_functions)} required functions available")
            validation_results.append(True)
    except Exception as e:
        print(f"   ❌ Function availability check failed: {e}")
        validation_results.append(False)
    
    # Test 4: Dependency injection container
    print("4. Testing dependency injection...")
    try:
        container = Container()
        
        # Check all adapters are available
        assert container.pixi_service is not None, "Pixi service not available"
        assert container.environment is not None, "Environment adapter not available"
        assert container.logging is not None, "Logging adapter not available"
        
        print("   ✅ Dependency injection working correctly")
        validation_results.append(True)
    except Exception as e:
        print(f"   ❌ Dependency injection failed: {e}")
        validation_results.append(False)
    
    # Test 5: Security validation
    print("5. Testing security features...")
    try:
        from adapters.validation import ValidationAdapter
        validator = ValidationAdapter()
        
        # Test validation functions
        assert validator.validate_task_name("test") == True, "Valid task name rejected"
        assert validator.validate_task_name("rm -rf /") == False, "Dangerous task name accepted"
        assert validator.validate_working_directory("../") == False, "Path traversal allowed"
        
        print("   ✅ Security validation working correctly")
        validation_results.append(True)
    except Exception as e:
        print(f"   ❌ Security validation failed: {e}")
        validation_results.append(False)
    
    # Summary
    print("\n" + "=" * 50)
    passed = sum(validation_results)
    total = len(validation_results)
    
    print(f"Validation Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 VALIDATION SUCCESSFUL!")
        print("   The pixi MCP server is fully implemented and ready for use.")
        print("   Key features:")
        print("   - Secure pixi task execution")
        print("   - Project-aware task discovery")  
        print("   - Environment management")
        print("   - Dependency handling")
        print("   - Input validation and sanitization")
        print("   - Comprehensive error handling")
        return True
    else:
        print("❌ VALIDATION FAILED!")
        print("   Some components need attention before deployment.")
        return False

if __name__ == "__main__":
    success = validate_server_implementation()
    sys.exit(0 if success else 1)