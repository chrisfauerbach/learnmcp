import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest
import redis

from knowledge_base import redis_client as rc


def make_search_result(docs):
    """Build a fake RediSearch Result with .docs list of SimpleNamespace objects."""
    result = SimpleNamespace(docs=[])
    for doc in docs:
        result.docs.append(SimpleNamespace(**doc))
    return result


# ── get_client() ──────────────────────────────────────────────────────

class TestGetClient:
    def test_creates_client_on_first_call(self):
        with patch("knowledge_base.redis_client.redis.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            client = rc.get_client()
            mock_from_url.assert_called_once_with(rc.REDIS_URL, decode_responses=True)
            assert client is mock_from_url.return_value

    def test_returns_cached_client_on_subsequent_calls(self):
        with patch("knowledge_base.redis_client.redis.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            c1 = rc.get_client()
            c2 = rc.get_client()
            assert c1 is c2
            mock_from_url.assert_called_once()


# ── ensure_index() ────────────────────────────────────────────────────

class TestEnsureIndex:
    def test_skips_when_index_exists(self):
        mock = MagicMock()
        with patch.object(rc, "get_client", return_value=mock):
            mock.ft.return_value.info.return_value = {"index_name": rc.INDEX_NAME}
            rc.ensure_index()
            mock.ft.return_value.info.assert_called_once()
            mock.ft.return_value.create_index.assert_not_called()

    def test_creates_index_when_missing(self):
        mock = MagicMock()
        with patch.object(rc, "get_client", return_value=mock):
            mock.ft.return_value.info.side_effect = redis.ResponseError("Unknown index")
            rc.ensure_index()
            mock.ft.return_value.create_index.assert_called_once()


# ── save_note() ───────────────────────────────────────────────────────

class TestSaveNote:
    def test_create_new_note(self, mock_redis):
        mock_redis.exists.return_value = False
        with patch("knowledge_base.redis_client.uuid.uuid4", return_value="test-uuid"):
            result = rc.save_note("Title", "Content", tags=["a", "b"])
        assert result["id"] == "test-uuid"
        assert result["title"] == "Title"
        assert result["content"] == "Content"
        assert result["tags"] == "a,b"
        mock_redis.hset.assert_called_once()

    def test_update_existing_note_pushes_history(self, mock_redis):
        mock_redis.exists.return_value = True
        mock_redis.hgetall.return_value = {
            "title": "Old",
            "content": "Old content",
            "tags": "",
            "created_at": "100.0",
            "updated_at": "100.0",
        }
        result = rc.save_note("New Title", "New Content", note_id="existing-id")
        mock_redis.lpush.assert_called_once()
        history_key = f"{rc.NOTE_PREFIX}existing-id:history"
        assert mock_redis.lpush.call_args[0][0] == history_key
        assert result["id"] == "existing-id"
        assert result["created_at"] == "100.0"

    def test_create_note_without_tags(self, mock_redis):
        mock_redis.exists.return_value = False
        with patch("knowledge_base.redis_client.uuid.uuid4", return_value="no-tags"):
            result = rc.save_note("Title", "Body")
        assert result["tags"] == ""

    def test_create_note_with_explicit_id(self, mock_redis):
        mock_redis.exists.return_value = False
        result = rc.save_note("Title", "Body", note_id="my-custom-id")
        assert result["id"] == "my-custom-id"
        key = f"{rc.NOTE_PREFIX}my-custom-id"
        mock_redis.hset.assert_called_once()
        assert mock_redis.hset.call_args[0][0] == key


# ── search_notes() ────────────────────────────────────────────────────

class TestSearchNotes:
    def test_returns_parsed_results(self, mock_redis, mock_ft):
        mock_ft.search.return_value = make_search_result([
            {"id": "note:abc", "title": "Hello", "content": "World", "tags": "x,y",
             "created_at": "1.0", "updated_at": "2.0"},
        ])
        results = rc.search_notes("hello")
        assert len(results) == 1
        assert results[0]["id"] == "abc"
        assert results[0]["tags"] == ["x", "y"]

    def test_escapes_special_characters(self, mock_redis, mock_ft):
        mock_ft.search.return_value = make_search_result([])
        rc.search_notes("hello@world")
        mock_ft.search.assert_called_once()

    def test_empty_results(self, mock_redis, mock_ft):
        mock_ft.search.return_value = make_search_result([])
        results = rc.search_notes("nonexistent")
        assert results == []


# ── find_by_tag() ─────────────────────────────────────────────────────

class TestFindByTag:
    def test_basic_tag_lookup(self, mock_redis, mock_ft):
        mock_ft.search.return_value = make_search_result([
            {"id": "note:t1", "title": "Tagged", "content": "Body", "tags": "python",
             "created_at": "1.0", "updated_at": "2.0"},
        ])
        results = rc.find_by_tag("python")
        assert len(results) == 1
        assert results[0]["id"] == "t1"

    def test_escapes_hyphens_and_spaces(self, mock_redis, mock_ft):
        mock_ft.search.return_value = make_search_result([])
        rc.find_by_tag("my-tag name")
        mock_ft.search.assert_called_once()


# ── list_notes() ──────────────────────────────────────────────────────

class TestListNotes:
    def test_wildcard_query(self, mock_redis, mock_ft):
        mock_ft.search.return_value = make_search_result([
            {"id": "note:n1", "title": "Note 1", "content": "C1", "tags": "",
             "created_at": "1.0", "updated_at": "2.0"},
        ])
        results = rc.list_notes()
        assert len(results) == 1
        mock_ft.search.assert_called_once()

    def test_custom_limit(self, mock_redis, mock_ft):
        mock_ft.search.return_value = make_search_result([])
        rc.list_notes(limit=5)
        mock_ft.search.assert_called_once()


# ── get_note_history() ────────────────────────────────────────────────

class TestGetNoteHistory:
    def test_returns_parsed_versions(self, mock_redis):
        mock_redis.lrange.return_value = [
            json.dumps({"title": "V1", "content": "C1", "tags": "a,b",
                        "created_at": "1.0", "updated_at": "2.0"}),
        ]
        versions = rc.get_note_history("nid")
        assert len(versions) == 1
        assert versions[0]["title"] == "V1"
        assert versions[0]["tags"] == ["a", "b"]

    def test_empty_history(self, mock_redis):
        mock_redis.lrange.return_value = []
        versions = rc.get_note_history("nid")
        assert versions == []

    def test_strips_whitespace_from_tags(self, mock_redis):
        mock_redis.lrange.return_value = [
            json.dumps({"title": "T", "content": "C", "tags": " a , b ",
                        "created_at": "1.0", "updated_at": "2.0"}),
        ]
        versions = rc.get_note_history("nid")
        assert versions[0]["tags"] == ["a", "b"]

    def test_empty_tags_string(self, mock_redis):
        mock_redis.lrange.return_value = [
            json.dumps({"title": "T", "content": "C", "tags": "",
                        "created_at": "1.0", "updated_at": "2.0"}),
        ]
        versions = rc.get_note_history("nid")
        assert versions[0]["tags"] == []


# ── restore_note_version() ───────────────────────────────────────────

class TestRestoreNoteVersion:
    def test_success_pushes_current_then_restores(self, mock_redis):
        mock_redis.exists.return_value = True
        old_version = {"title": "Old", "content": "OldC", "tags": "t",
                       "created_at": "1.0", "updated_at": "2.0"}
        mock_redis.lindex.return_value = json.dumps(old_version)
        mock_redis.hgetall.return_value = {
            "title": "Current", "content": "CurC", "tags": "",
            "created_at": "1.0", "updated_at": "3.0",
        }
        result = rc.restore_note_version("nid", 0)
        assert result["title"] == "Old"
        assert result["content"] == "OldC"
        assert result["id"] == "nid"
        mock_redis.lpush.assert_called_once()
        mock_redis.hset.assert_called_once()

    def test_raises_when_note_not_found(self, mock_redis):
        mock_redis.exists.return_value = False
        with pytest.raises(ValueError, match="not found"):
            rc.restore_note_version("missing", 0)

    def test_raises_when_version_not_found(self, mock_redis):
        mock_redis.exists.return_value = True
        mock_redis.lindex.return_value = None
        with pytest.raises(ValueError, match="Version index"):
            rc.restore_note_version("nid", 99)


# ── delete_note() ─────────────────────────────────────────────────────

class TestDeleteNote:
    def test_existing_note_returns_true(self, mock_redis):
        mock_redis.delete.return_value = 1
        assert rc.delete_note("nid") is True

    def test_missing_note_returns_false(self, mock_redis):
        mock_redis.delete.return_value = 0
        assert rc.delete_note("nid") is False


# ── get_all_tags() ────────────────────────────────────────────────────

class TestGetAllTags:
    def test_returns_sorted_unique_tags(self, mock_redis, mock_ft):
        mock_ft.search.return_value = make_search_result([
            {"id": "note:1", "tags": "python,redis"},
            {"id": "note:2", "tags": "redis,testing"},
        ])
        tags = rc.get_all_tags()
        assert tags == ["python", "redis", "testing"]

    def test_ignores_empty_tags(self, mock_redis, mock_ft):
        mock_ft.search.return_value = make_search_result([
            {"id": "note:1", "tags": ""},
            {"id": "note:2", "tags": "valid"},
        ])
        tags = rc.get_all_tags()
        assert tags == ["valid"]

    def test_no_notes(self, mock_redis, mock_ft):
        mock_ft.search.return_value = make_search_result([])
        tags = rc.get_all_tags()
        assert tags == []


# ── get_stats() ───────────────────────────────────────────────────────

class TestGetStats:
    def test_normal_stats(self, mock_redis, mock_ft):
        mock_ft.info.return_value = {"num_docs": "5"}
        mock_ft.search.return_value = make_search_result([
            {"id": "note:1", "tags": "a,b"},
        ])
        stats = rc.get_stats()
        assert stats["total_notes"] == 5
        assert stats["total_tags"] == 2
        assert stats["index_name"] == rc.INDEX_NAME

    def test_zero_notes(self, mock_redis, mock_ft):
        mock_ft.info.return_value = {"num_docs": "0"}
        mock_ft.search.return_value = make_search_result([])
        stats = rc.get_stats()
        assert stats["total_notes"] == 0
        assert stats["total_tags"] == 0


# ── _escape_query() ──────────────────────────────────────────────────

class TestEscapeQuery:
    def test_no_special_chars(self):
        assert rc._escape_query("hello world") == "hello world"

    def test_all_special_chars(self):
        for ch in r"@!{}()|-=>[]:;~*":
            assert f"\\{ch}" in rc._escape_query(ch)

    def test_mixed_content(self):
        result = rc._escape_query("hello@world")
        assert result == "hello\\@world"

    def test_empty_string(self):
        assert rc._escape_query("") == ""


# ── _parse_results() ─────────────────────────────────────────────────

class TestParseResults:
    def test_basic_parsing(self):
        results = make_search_result([
            {"id": "note:abc", "title": "T", "content": "C", "tags": "x,y",
             "created_at": "1.0", "updated_at": "2.0"},
        ])
        parsed = rc._parse_results(results)
        assert len(parsed) == 1
        assert parsed[0]["id"] == "abc"
        assert parsed[0]["title"] == "T"
        assert parsed[0]["tags"] == ["x", "y"]

    def test_empty_tags(self):
        results = make_search_result([
            {"id": "note:a", "title": "T", "content": "C", "tags": "",
             "created_at": "1.0", "updated_at": "2.0"},
        ])
        parsed = rc._parse_results(results)
        assert parsed[0]["tags"] == []

    def test_prefix_stripping(self):
        results = make_search_result([
            {"id": "note:my-id", "title": "T", "content": "C", "tags": "",
             "created_at": "1.0", "updated_at": "2.0"},
        ])
        parsed = rc._parse_results(results)
        assert parsed[0]["id"] == "my-id"

    def test_empty_docs(self):
        results = make_search_result([])
        parsed = rc._parse_results(results)
        assert parsed == []

    def test_missing_attributes_use_defaults(self):
        results = make_search_result([{"id": "note:x"}])
        parsed = rc._parse_results(results)
        assert parsed[0]["title"] == ""
        assert parsed[0]["content"] == ""
        assert parsed[0]["tags"] == []
        assert parsed[0]["created_at"] == ""
        assert parsed[0]["updated_at"] == ""
