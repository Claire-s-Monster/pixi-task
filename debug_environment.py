#!/usr/bin/env python3
"""
Debug the environment the MCP server sees by adding a debug endpoint.
"""

import os
import sys
from pathlib import Path

# Add src to path  
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

# Test what environment subprocess sees
import subprocess

def test_subprocess_environment():
    """Test what environment subprocess.run sees."""
    print("=== Subprocess Environment Test ===")
    
    # Test 1: Check environment variables
    print("\n1. Environment Variables via subprocess:")
    result = subprocess.run(
        ["bash", "-c", "echo BASH_ENV=$BASH_ENV; echo CLAUDECODE_PATH=$CLAUDECODE_PATH; echo PATH=$PATH | head -c 200"],
        capture_output=True,
        text=True,
        env=os.environ.copy()
    )
    print(f"   stdout: {result.stdout}")
    print(f"   stderr: {result.stderr}")
    
    # Test 2: Check if any claudecode functions are in PATH
    print("\n2. ClaudeCode functions in PATH:")
    result = subprocess.run(
        ["bash", "-c", "compgen -c | grep claudecode | head -5"],
        capture_output=True,
        text=True,
        env=os.environ.copy()
    )
    print(f"   Found functions: {result.stdout.strip()}")
    
    # Test 3: Check claudecode paths
    print("\n3. Checking CLAUDECODE_PATH directories:")
    claudecode_path = os.environ.get('CLAUDECODE_PATH', '')
    if claudecode_path:
        paths = claudecode_path.split(':')
        for i, path in enumerate(paths[:5]):  # Check first 5 paths
            if os.path.isdir(path):
                try:
                    files = os.listdir(path)
                    claudecode_files = [f for f in files if f.startswith('claudecode_')]
                    print(f"   Path {i+1}: {path} -> {len(claudecode_files)} claudecode files")
                    if claudecode_files:
                        print(f"      Examples: {claudecode_files[:3]}")
                except Exception as e:
                    print(f"   Path {i+1}: {path} -> Error: {e}")
            else:
                print(f"   Path {i+1}: {path} -> Directory not found")
    else:
        print("   CLAUDECODE_PATH not set")
    
    # Test 4: Try to find a specific claudecode function
    print("\n4. Testing specific function discovery:")
    test_functions = ["claudecode_help", "claudecode_system_info", "claudecode_version"]
    
    for func in test_functions:
        result = subprocess.run(
            ["which", func],
            capture_output=True,
            text=True,
            env=os.environ.copy()
        )
        if result.returncode == 0:
            print(f"   {func}: FOUND at {result.stdout.strip()}")
        else:
            print(f"   {func}: NOT FOUND in PATH")

if __name__ == "__main__":
    test_subprocess_environment()