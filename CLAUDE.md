# CLAUDE.md

## Project

Redis-backed MCP server providing Claude with a persistent knowledge base. Python 3.12, FastMCP, RediSearch.

## Structure

- `src/knowledge_base/server.py` — MCP layer (tools, resources, prompts via `@mcp.tool()` etc.)
- `src/knowledge_base/redis_client.py` — Data layer (all Redis/RediSearch operations)
- `src/knowledge_base/__main__.py` — Entrypoint (`mcp.run()`)
- `docker-compose.yml` — Redis + MCP server orchestration
- `Dockerfile` — Python 3.12-slim container
- `claude_mcp_config.json` — MCP server launch config for Claude Code

## Key Conventions

- Two-layer architecture: `server.py` is a thin MCP interface that delegates to `redis_client.py`. Keep business logic in the data layer.
- Notes are stored as Redis hashes with prefix `note:<uuid>`. RediSearch index is `idx:notes`.
- Tags are stored as comma-separated strings in Redis, parsed into lists at the API boundary.
- Version history uses Redis Lists at `note:<uuid>:history`. Always push the current state before overwriting.

## Running

```bash
docker compose up -d          # Start Redis
docker compose run --rm -i mcp-server  # Run MCP server (stdio)
```

## Dependencies

Defined in `pyproject.toml`: `mcp[cli]`, `redis>=5.0`. No dev dependencies yet.
