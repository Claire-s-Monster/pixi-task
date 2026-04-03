#!/usr/bin/env python3
"""
Simple MCP client to test pixi-shell server protocol.
"""

import json
import subprocess
import sys
import time

def test_mcp_server():
    """Test MCP server with basic protocol messages."""
    print("🔌 Testing MCP Protocol Communication")
    print("=" * 50)
    
    # Start the server process
    server_cmd = [
        sys.executable, "-m", "pixi_shell.server"
    ]
    
    try:
        # Start server with pixi environment
        env = {"PYTHONPATH": "src"}
        proc = subprocess.Popen(
            ["pixi", "run", "-e", "quality"] + server_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd="/home/memento/ClaudeCode/Servers/pixi-shell/development"
        )
        
        # Wait a moment for server to start
        time.sleep(2)
        
        # Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        }
        
        print("📤 Sending initialize request...")
        proc.stdin.write(json.dumps(init_request) + "\n")
        proc.stdin.flush()
        
        # Read response (with timeout)
        try:
            response_line = proc.stdout.readline()
            if response_line:
                response = json.loads(response_line.strip())
                print("📥 Received response:", response)
                
                if response.get("id") == 1 and "result" in response:
                    print("✅ Initialize successful!")
                    
                    # Send tools/list request
                    tools_request = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {}
                    }
                    
                    print("📤 Sending tools/list request...")
                    proc.stdin.write(json.dumps(tools_request) + "\n")
                    proc.stdin.flush()
                    
                    # Read tools response
                    tools_response_line = proc.stdout.readline()
                    if tools_response_line:
                        tools_response = json.loads(tools_response_line.strip())
                        print("📥 Received tools response:", tools_response)
                        
                        if "result" in tools_response and "tools" in tools_response["result"]:
                            tools = tools_response["result"]["tools"]
                            print(f"✅ Found {len(tools)} tools:")
                            for tool in tools:
                                print(f"   - {tool.get('name', 'unknown')}: {tool.get('description', 'no description')[:60]}...")
                            
                            return True
                else:
                    print("❌ Initialize failed:", response)
            else:
                print("❌ No response received")
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error: {e}")
            print(f"Raw response: {response_line}")
        except Exception as e:
            print(f"❌ Error reading response: {e}")
        
    except Exception as e:
        print(f"❌ Error starting server: {e}")
    
    finally:
        # Clean up
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except:
            proc.kill()
    
    return False

if __name__ == "__main__":
    success = test_mcp_server()
    if success:
        print("\n🎉 MCP protocol test successful!")
        print("   Server is ready for Claude Code integration")
    else:
        print("\n❌ MCP protocol test failed")
        print("   Check server configuration and dependencies")