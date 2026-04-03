#!/usr/bin/env python3
"""
Test the fixed task listing functionality.
"""

import sys
sys.path.insert(0, 'src')

from adapters.project import PixiProjectAdapter
from adapters.environment import EnvironmentAdapter
from adapters.logging import LoggingAdapter

def test_task_listing():
    """Test task listing on real pixi projects."""
    print("📋 Testing Fixed Task Listing")
    print("=" * 50)
    
    env = EnvironmentAdapter('/home/memento/ClaudeCode/Servers/agent-cache/development')
    log = LoggingAdapter()
    project = PixiProjectAdapter(env, log)
    
    # Test agent-cache project
    agent_cache_path = '/home/memento/ClaudeCode/Servers/agent-cache/development'
    print(f"📁 Agent-cache tasks:")
    tasks = project.get_available_tasks(agent_cache_path)
    print(f"   Found {len(tasks)} tasks:")
    for name, cmd in list(tasks.items())[:5]:  # Show first 5 tasks
        print(f"     - {name}: {cmd[:60]}{'...' if len(cmd) > 60 else ''}")
    if len(tasks) > 5:
        print(f"     ... and {len(tasks) - 5} more tasks")
    
    # Test pixi-shell project  
    pixi_shell_path = '/home/memento/ClaudeCode/Servers/pixi-shell/development'
    print(f"\n📁 Pixi-shell tasks:")
    tasks = project.get_available_tasks(pixi_shell_path)
    print(f"   Found {len(tasks)} tasks:")
    for name, cmd in list(tasks.items())[:5]:  # Show first 5 tasks
        print(f"     - {name}: {cmd[:60]}{'...' if len(cmd) > 60 else ''}")
    if len(tasks) > 5:
        print(f"     ... and {len(tasks) - 5} more tasks")
    
    return True

if __name__ == "__main__":
    try:
        test_task_listing()
        print("\n✅ Task listing test completed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()