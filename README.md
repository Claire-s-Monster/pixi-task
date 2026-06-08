# pixi-task

A secure MCP server providing controlled access to pixi tasks and commands, eliminating agent bash circumvention.

## Overview

Exposes 11 pixi tools through 4 lean meta-tools (`discover_tools`, `get_tool_spec`, `execute_tool`, `server_info`) for ~95% context savings compared to a traditional MCP server that advertises every tool individually.

Two transports are supported:

- **stdio** — exposes the full registry (11 tools).
- **HTTP** — gates the surface to `core` + `extended` complexity (7 tools); use this for daemonised deployments. Default port: `4101`.

Both transports surface a `server_info` meta-tool for self-identification (name, version, transport label, live tool counts, source URLs).

## Development

```bash
pixi install -e quality
pixi run test
pixi run lint
pixi run format
pixi run typecheck
```

The HTTP server can be run directly:

```bash
pixi run http-server --port 4101
```

For background operation, the repo ships a systemd user unit (see `~/.config/systemd/user/pixi-shell.service` for the current installed name; this will be renamed to `pixi-task.service` in a follow-up commit).

## Available Tasks

The canonical task list lives in `[tool.pixi.tasks]` in `pyproject.toml`. Key tasks:

| Task | Purpose |
|------|---------|
| `test` | pytest suite (timeout 30s) |
| `test-cov` | pytest with coverage |
| `lint` | ruff lint (F + E9 rules) |
| `lint-full` | full ruff lint |
| `format` | ruff format |
| `typecheck` | mypy on `src/` |
| `quality` | combined lint + format-check + typecheck |
| `http-server` | start the HTTP MCP transport |
| `lean-server` | start the stdio MCP transport |

Run `pixi task list` to see every task.

## License

MIT — see [LICENSE](LICENSE).
