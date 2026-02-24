from mcp.server.fastmcp import FastMCP

from knowledge_base import redis_client

mcp = FastMCP("knowledge-base")

# ── Tools ────────────────────────────────────────────────────────────────


@mcp.tool()
def save_note(
    title: str,
    content: str,
    tags: list[str] | None = None,
    note_id: str | None = None,
) -> dict:
    """Create or update a note in the knowledge base.

    Args:
        title: Note title
        content: Note body text
        tags: Optional list of tags for categorization
        note_id: Optional ID to update an existing note; omit to create new
    """
    return redis_client.save_note(title, content, tags, note_id)


@mcp.tool()
def search_notes(query: str, limit: int = 10) -> list[dict]:
    """Full-text search across note titles and content.

    Args:
        query: Search terms
        limit: Max results to return (default 10)
    """
    return redis_client.search_notes(query, limit)


@mcp.tool()
def find_by_tag(tag: str, limit: int = 10) -> list[dict]:
    """Find all notes with a specific tag.

    Args:
        tag: Tag to filter by
        limit: Max results to return (default 10)
    """
    return redis_client.find_by_tag(tag, limit)


@mcp.tool()
def list_notes(limit: int = 20) -> list[dict]:
    """List all notes, most recently updated first.

    Args:
        limit: Max results to return (default 20)
    """
    return redis_client.list_notes(limit)


@mcp.tool()
def get_note_history(note_id: str, limit: int = 10) -> list[dict]:
    """View previous versions of a note.

    Args:
        note_id: The UUID of the note
        limit: Max versions to return (default 10)
    """
    return redis_client.get_note_history(note_id, limit)


@mcp.tool()
def restore_note_version(note_id: str, version_index: int) -> dict:
    """Restore a note to a previous version.

    Args:
        note_id: The UUID of the note
        version_index: Index of the version to restore (0 = most recent previous version)
    """
    return redis_client.restore_note_version(note_id, version_index)


@mcp.tool()
def delete_note(note_id: str) -> str:
    """Delete a note by its ID.

    Args:
        note_id: The UUID of the note to delete
    """
    if redis_client.delete_note(note_id):
        return f"Deleted note {note_id}"
    return f"Note {note_id} not found"


# ── Resources ────────────────────────────────────────────────────────────


@mcp.resource("notes://tags")
def tags_resource() -> str:
    """List all unique tags currently in use."""
    tags = redis_client.get_all_tags()
    if not tags:
        return "No tags found."
    return "\n".join(tags)


@mcp.resource("notes://stats")
def stats_resource() -> str:
    """Knowledge base statistics: note count, tag count, index info."""
    stats = redis_client.get_stats()
    lines = [
        f"Total notes: {stats['total_notes']}",
        f"Total tags:  {stats['total_tags']}",
        f"Tags:        {', '.join(stats['tags']) if stats['tags'] else '(none)'}",
        f"Index:       {stats['index_name']}",
    ]
    return "\n".join(lines)


# ── Prompts ──────────────────────────────────────────────────────────────


@mcp.prompt()
def summarize_notes(query: str = "") -> str:
    """Summarize notes matching a search query.

    Args:
        query: Search terms to filter notes (empty = all notes)
    """
    if query:
        notes = redis_client.search_notes(query, limit=50)
    else:
        notes = redis_client.list_notes(limit=50)

    if not notes:
        return "No notes found. There is nothing to summarize."

    parts = ["Summarize the following notes concisely:\n"]
    for n in notes:
        tags = ", ".join(n["tags"]) if n["tags"] else "none"
        parts.append(f"## {n['title']} [tags: {tags}]\n{n['content']}\n")

    return "\n".join(parts)
