# knowledge-base

A Redis-backed MCP server that gives Claude a persistent knowledge base with full-text search, tagging, and version history.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (with Compose v2)

## Setup

1. Start Redis:

```bash
docker compose up -d
```

2. Copy the MCP config into your Claude Code settings, updating the path to `docker-compose.yml`:

```json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "docker",
      "args": [
        "compose",
        "-f", "/absolute/path/to/docker-compose.yml",
        "run", "--rm", "-i",
        "mcp-server"
      ]
    }
  }
}
```

3. Restart Claude Code. The knowledge-base tools will appear automatically.

## Tools

| Tool | Description |
|------|-------------|
| `save_note` | Create or update a note (with optional tags) |
| `search_notes` | Full-text search across titles and content |
| `find_by_tag` | Find notes by tag |
| `list_notes` | List all notes, most recently updated first |
| `delete_note` | Delete a note and its history |
| `get_note_history` | View previous versions of a note |
| `restore_note_version` | Restore a note to a previous version |

## Resources

- `notes://tags` — all unique tags in use
- `notes://stats` — note count, tag count, index info

## Prompts

- `summarize_notes` — generates a prompt to summarize notes matching a query

## Architecture

```
src/knowledge_base/
├── __main__.py      # Entrypoint
├── server.py        # MCP tool/resource/prompt definitions (FastMCP)
└── redis_client.py  # Redis data layer (RediSearch for full-text search)
```

The server communicates with Claude Code over stdio. Docker Compose runs both Redis (with RediSearch) and the MCP server, connected via an internal network.

## Version History

Every note update automatically preserves the previous version. You can browse history with `get_note_history` and roll back with `restore_note_version`. Even restores are non-destructive — the current state is saved to history before the rollback.

## Services

| Service | Port | Description |
|---------|------|-------------|
| `redis` | 6379 | Redis with RediSearch |
| `redis` | 8002 | RedisInsight web UI |
| `mcp-server` | — | MCP server (stdio, on-demand only) |

Data is persisted in a Docker named volume (`redis-data`).
