#!/usr/bin/env python3
"""
Test the fixed project detection logic.
"""

import sys
sys.path.insert(0, 'src')

from adapters.project import PixiProjectAdapter
from adapters.environment import EnvironmentAdapter
from adapters.logging import LoggingAdapter

def test_project_detection():
    """Test project detection on real pixi projects."""
    print("🔍 Testing Fixed Project Detection")
    print("=" * 50)
    
    env = EnvironmentAdapter('/home/memento/ClaudeCode/Servers/agent-cache/development')
    log = LoggingAdapter()
    project = PixiProjectAdapter(env, log)
    
    # Test agent-cache project
    agent_cache_path = '/home/memento/ClaudeCode/Servers/agent-cache/development'
    print(f"📁 Agent-cache ({agent_cache_path}):")
    is_pixi = project.is_pixi_project(agent_cache_path)
    print(f"   Is pixi project: {is_pixi}")
    
    if is_pixi:
        info = project.get_project_info(agent_cache_path)
        print(f"   Project name: {info.project_name}")
        print(f"   Dependencies: {len(info.dependencies)}")
        print(f"   Available tasks: {len(info.available_tasks)}")
    
    # Test pixi-shell project
    pixi_shell_path = '/home/memento/ClaudeCode/Servers/pixi-shell/development'
    print(f"\n📁 Pixi-shell ({pixi_shell_path}):")
    is_pixi = project.is_pixi_project(pixi_shell_path)
    print(f"   Is pixi project: {is_pixi}")
    
    if is_pixi:
        info = project.get_project_info(pixi_shell_path)
        print(f"   Project name: {info.project_name}")
        print(f"   Dependencies: {len(info.dependencies)}")
        print(f"   Available tasks: {len(info.available_tasks)}")
    
    # Test non-pixi directory
    home_path = '/home/memento'
    print(f"\n📁 Non-pixi directory ({home_path}):")
    is_pixi = project.is_pixi_project(home_path)
    print(f"   Is pixi project: {is_pixi}")
    
    return True

if __name__ == "__main__":
    try:
        test_project_detection()
        print("\n✅ Project detection test completed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()