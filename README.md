# ClaudeCode Shell MCP Server

A secure MCP server providing controlled access to claudecode_* functions, replacing unrestricted Bash tool usage with validated, safe function execution.

## 🚀 Quick Start

```bash
# Install dependencies
pixi install

# Start the MCP server
pixi run mcp-server
```

## 🔒 Security Model

- **Function Whitelist**: Only allows functions starting with `claudecode_`
- **Argument Validation**: Sanitizes and validates all function arguments
- **Timeout Protection**: Enforces execution timeouts (1-300 seconds)
- **Audit Logging**: Comprehensive execution logging for security

## 🔄 Migration Pattern

Replace unsafe Bash usage with secure MCP calls:

```python
# Before (risky)
result = Bash("claudecode_system_info load")

# After (secure)  
result = mcp__claudecode_shell__execute_claudecode_function("claudecode_system_info", ["load"])
```

## 🛠 Core Functions

- `execute_claudecode_function()` - Secure function execution
- `list_available_functions()` - Function discovery  
- `validate_function_exists()` - Function validation
- `get_execution_stats()` - Performance monitoring
- `get_system_health()` - Health checks

## 📋 Function Categories

- `atomic` - Atomic design and refactoring
- `git` - Git workflow and repository operations
- `python` - Python quality and analysis
- `quality` - Quality assurance and testing
- `system` - System information and resources
- `pixi` - PIXI package management
- `ci` - CI/CD workflows
- `security` - Security scanning

## ⚡ Performance

- Sub-100ms execution overhead vs direct Bash
- Identical stdout/stderr/exit_code behavior
- Full backward compatibility with existing functions
- Comprehensive caching for function discovery

## 🏗 Architecture

Built using hexagonal architecture with:
- **Core Domain**: Security models and business logic
- **Ports**: Abstract interfaces for external dependencies  
- **Adapters**: Concrete implementations for execution, logging, etc.
- **FastMCP**: High-performance MCP server framework