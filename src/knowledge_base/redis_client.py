import json
import os
import time
import uuid

import redis
from redis.commands.search.field import NumericField, TagField, TextField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
NOTE_PREFIX = "note:"
INDEX_NAME = "idx:notes"

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def ensure_index() -> None:
    """Create the RediSearch index if it doesn't exist."""
    r = get_client()
    try:
        r.ft(INDEX_NAME).info()
    except redis.ResponseError:
        schema = (
            TextField("title", weight=2.0),
            TextField("content"),
            TagField("tags"),
            NumericField("created_at", sortable=True),
            NumericField("updated_at", sortable=True),
        )
        definition = IndexDefinition(prefix=[NOTE_PREFIX], index_type=IndexType.HASH)
        r.ft(INDEX_NAME).create_index(schema, definition=definition)


def save_note(title: str, content: str, tags: list[str] | None = None, note_id: str | None = None) -> dict:
    """Create or update a note. Returns the saved note with its ID."""
    r = get_client()
    ensure_index()

    now = time.time()
    if note_id is None:
        note_id = str(uuid.uuid4())

    key = f"{NOTE_PREFIX}{note_id}"
    existing = r.exists(key)

    note = {
        "title": title,
        "content": content,
        "tags": ",".join(tags) if tags else "",
        "updated_at": now,
    }
    if not existing:
        note["created_at"] = now
    else:
        old = r.hgetall(key)
        r.lpush(f"{key}:history", json.dumps(old))
        note["created_at"] = old.get("created_at", now)

    r.hset(key, mapping=note)
    return {"id": note_id, **note}


def search_notes(query_text: str, limit: int = 10) -> list[dict]:
    """Full-text search across title and content."""
    r = get_client()
    ensure_index()

    escaped = _escape_query(query_text)
    q = Query(escaped).paging(0, limit).sort_by("updated_at", asc=False)
    results = r.ft(INDEX_NAME).search(q)
    return _parse_results(results)


def find_by_tag(tag: str, limit: int = 10) -> list[dict]:
    """Find notes with a specific tag."""
    r = get_client()
    ensure_index()

    escaped_tag = tag.replace("-", "\\-").replace(" ", "\\ ")
    q = Query(f"@tags:{{{escaped_tag}}}").paging(0, limit).sort_by("updated_at", asc=False)
    results = r.ft(INDEX_NAME).search(q)
    return _parse_results(results)


def list_notes(limit: int = 20) -> list[dict]:
    """List all notes, most recently updated first."""
    r = get_client()
    ensure_index()

    q = Query("*").paging(0, limit).sort_by("updated_at", asc=False)
    results = r.ft(INDEX_NAME).search(q)
    return _parse_results(results)


def get_note_history(note_id: str, limit: int = 10) -> list[dict]:
    """Return previous versions of a note, most recent first."""
    r = get_client()
    history_key = f"{NOTE_PREFIX}{note_id}:history"
    raw_entries = r.lrange(history_key, 0, limit - 1)
    versions = []
    for entry in raw_entries:
        data = json.loads(entry)
        tags_raw = data.get("tags", "")
        versions.append({
            "title": data.get("title", ""),
            "content": data.get("content", ""),
            "tags": [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else [],
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
        })
    return versions


def restore_note_version(note_id: str, version_index: int) -> dict:
    """Restore a note to a previous version by index. Returns the restored note."""
    r = get_client()
    history_key = f"{NOTE_PREFIX}{note_id}:history"
    key = f"{NOTE_PREFIX}{note_id}"

    if not r.exists(key):
        raise ValueError(f"Note {note_id} not found")

    raw = r.lindex(history_key, version_index)
    if raw is None:
        raise ValueError(f"Version index {version_index} not found for note {note_id}")

    old_version = json.loads(raw)

    # Push current state to history before restoring
    current = r.hgetall(key)
    r.lpush(history_key, json.dumps(current))

    # Overwrite with restored version, but update the timestamp
    now = time.time()
    note = {
        "title": old_version.get("title", ""),
        "content": old_version.get("content", ""),
        "tags": old_version.get("tags", ""),
        "created_at": old_version.get("created_at", now),
        "updated_at": now,
    }
    r.hset(key, mapping=note)
    return {"id": note_id, **note}


def delete_note(note_id: str) -> bool:
    """Delete a note and its version history. Returns True if the note existed."""
    r = get_client()
    key = f"{NOTE_PREFIX}{note_id}"
    history_key = f"{key}:history"
    r.delete(history_key)
    return r.delete(key) > 0


def get_all_tags() -> list[str]:
    """Return all unique tags currently in use."""
    r = get_client()
    ensure_index()

    results = r.ft(INDEX_NAME).search(Query("*").paging(0, 1000).return_field("tags"))
    tags: set[str] = set()
    for doc in results.docs:
        raw = getattr(doc, "tags", "")
        if raw:
            for t in raw.split(","):
                stripped = t.strip()
                if stripped:
                    tags.add(stripped)
    return sorted(tags)


def get_stats() -> dict:
    """Return note count, tag count, and index info."""
    r = get_client()
    ensure_index()

    info = r.ft(INDEX_NAME).info()
    num_docs = int(info.get("num_docs", info.get("num_docs", 0)))
    tags = get_all_tags()
    return {
        "total_notes": num_docs,
        "total_tags": len(tags),
        "tags": tags,
        "index_name": INDEX_NAME,
    }


def _escape_query(text: str) -> str:
    """Escape special RediSearch characters in user input."""
    special = r"@!{}()|-=>[]:;~*"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def _parse_results(results) -> list[dict]:
    """Convert RediSearch results to a list of dicts."""
    notes = []
    for doc in results.docs:
        note_id = doc.id.removeprefix(NOTE_PREFIX)
        tags_raw = getattr(doc, "tags", "")
        notes.append({
            "id": note_id,
            "title": getattr(doc, "title", ""),
            "content": getattr(doc, "content", ""),
            "tags": [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else [],
            "created_at": getattr(doc, "created_at", ""),
            "updated_at": getattr(doc, "updated_at", ""),
        })
    return notes
