from unittest.mock import patch, MagicMock

import pytest

from knowledge_base import server, redis_client


# ── Tools ─────────────────────────────────────────────────────────────


class TestSaveNote:
    @patch.object(redis_client, "save_note")
    def test_delegates_to_redis_client(self, mock_save):
        mock_save.return_value = {"id": "abc", "title": "T", "content": "C", "tags": "a,b"}
        result = server.save_note("T", "C", tags=["a", "b"], note_id=None)
        mock_save.assert_called_once_with("T", "C", ["a", "b"], None)
        assert result["id"] == "abc"

    @patch.object(redis_client, "save_note")
    def test_passes_note_id_for_update(self, mock_save):
        mock_save.return_value = {"id": "existing"}
        server.save_note("T", "C", note_id="existing")
        mock_save.assert_called_once_with("T", "C", None, "existing")

    @patch.object(redis_client, "save_note")
    def test_defaults_optional_params(self, mock_save):
        mock_save.return_value = {"id": "new"}
        server.save_note("T", "C")
        mock_save.assert_called_once_with("T", "C", None, None)


class TestSearchNotes:
    @patch.object(redis_client, "search_notes")
    def test_delegates_with_defaults(self, mock_search):
        mock_search.return_value = [{"id": "1"}]
        result = server.search_notes("hello")
        mock_search.assert_called_once_with("hello", 10)
        assert result == [{"id": "1"}]

    @patch.object(redis_client, "search_notes")
    def test_custom_limit(self, mock_search):
        mock_search.return_value = []
        server.search_notes("q", limit=5)
        mock_search.assert_called_once_with("q", 5)


class TestFindByTag:
    @patch.object(redis_client, "find_by_tag")
    def test_delegates_with_defaults(self, mock_find):
        mock_find.return_value = [{"id": "t1"}]
        result = server.find_by_tag("python")
        mock_find.assert_called_once_with("python", 10)
        assert result == [{"id": "t1"}]

    @patch.object(redis_client, "find_by_tag")
    def test_custom_limit(self, mock_find):
        mock_find.return_value = []
        server.find_by_tag("go", limit=3)
        mock_find.assert_called_once_with("go", 3)


class TestListNotes:
    @patch.object(redis_client, "list_notes")
    def test_delegates_with_defaults(self, mock_list):
        mock_list.return_value = [{"id": "n1"}]
        result = server.list_notes()
        mock_list.assert_called_once_with(20)
        assert result == [{"id": "n1"}]

    @patch.object(redis_client, "list_notes")
    def test_custom_limit(self, mock_list):
        mock_list.return_value = []
        server.list_notes(limit=5)
        mock_list.assert_called_once_with(5)


class TestGetNoteHistory:
    @patch.object(redis_client, "get_note_history")
    def test_delegates_with_defaults(self, mock_hist):
        mock_hist.return_value = [{"title": "V1"}]
        result = server.get_note_history("nid")
        mock_hist.assert_called_once_with("nid", 10)
        assert result == [{"title": "V1"}]

    @patch.object(redis_client, "get_note_history")
    def test_custom_limit(self, mock_hist):
        mock_hist.return_value = []
        server.get_note_history("nid", limit=3)
        mock_hist.assert_called_once_with("nid", 3)


class TestRestoreNoteVersion:
    @patch.object(redis_client, "restore_note_version")
    def test_delegates_correctly(self, mock_restore):
        mock_restore.return_value = {"id": "nid", "title": "Restored"}
        result = server.restore_note_version("nid", 0)
        mock_restore.assert_called_once_with("nid", 0)
        assert result["title"] == "Restored"

    @patch.object(redis_client, "restore_note_version")
    def test_propagates_value_error(self, mock_restore):
        mock_restore.side_effect = ValueError("not found")
        with pytest.raises(ValueError, match="not found"):
            server.restore_note_version("bad", 99)


class TestDeleteNote:
    @patch.object(redis_client, "delete_note")
    def test_existing_note_returns_deleted_message(self, mock_del):
        mock_del.return_value = True
        result = server.delete_note("abc")
        assert result == "Deleted note abc"
        mock_del.assert_called_once_with("abc")

    @patch.object(redis_client, "delete_note")
    def test_missing_note_returns_not_found_message(self, mock_del):
        mock_del.return_value = False
        result = server.delete_note("xyz")
        assert result == "Note xyz not found"


# ── Resources ─────────────────────────────────────────────────────────


class TestTagsResource:
    @patch.object(redis_client, "get_all_tags")
    def test_returns_joined_tags(self, mock_tags):
        mock_tags.return_value = ["python", "redis", "testing"]
        result = server.tags_resource()
        assert result == "python\nredis\ntesting"

    @patch.object(redis_client, "get_all_tags")
    def test_empty_tags_returns_message(self, mock_tags):
        mock_tags.return_value = []
        result = server.tags_resource()
        assert result == "No tags found."

    @patch.object(redis_client, "get_all_tags")
    def test_single_tag(self, mock_tags):
        mock_tags.return_value = ["solo"]
        result = server.tags_resource()
        assert result == "solo"


class TestStatsResource:
    @patch.object(redis_client, "get_stats")
    def test_formats_stats(self, mock_stats):
        mock_stats.return_value = {
            "total_notes": 10,
            "total_tags": 3,
            "tags": ["a", "b", "c"],
            "index_name": "idx:notes",
        }
        result = server.stats_resource()
        assert "Total notes: 10" in result
        assert "Total tags:  3" in result
        assert "a, b, c" in result
        assert "idx:notes" in result

    @patch.object(redis_client, "get_stats")
    def test_no_tags_shows_none(self, mock_stats):
        mock_stats.return_value = {
            "total_notes": 0,
            "total_tags": 0,
            "tags": [],
            "index_name": "idx:notes",
        }
        result = server.stats_resource()
        assert "(none)" in result
        assert "Total notes: 0" in result


# ── Prompts ───────────────────────────────────────────────────────────


class TestSummarizeNotes:
    @patch.object(redis_client, "search_notes")
    def test_with_query_uses_search(self, mock_search):
        mock_search.return_value = [
            {"title": "Note 1", "content": "Body 1", "tags": ["a"]},
        ]
        result = server.summarize_notes(query="hello")
        mock_search.assert_called_once_with("hello", limit=50)
        assert "Note 1" in result
        assert "Body 1" in result
        assert "a" in result

    @patch.object(redis_client, "list_notes")
    def test_empty_query_uses_list(self, mock_list):
        mock_list.return_value = [
            {"title": "All", "content": "Everything", "tags": []},
        ]
        result = server.summarize_notes(query="")
        mock_list.assert_called_once_with(limit=50)
        assert "All" in result
        assert "none" in result

    @patch.object(redis_client, "list_notes")
    def test_no_notes_returns_nothing_message(self, mock_list):
        mock_list.return_value = []
        result = server.summarize_notes()
        assert result == "No notes found. There is nothing to summarize."

    @patch.object(redis_client, "search_notes")
    def test_multiple_notes_formatted(self, mock_search):
        mock_search.return_value = [
            {"title": "A", "content": "Ca", "tags": ["x"]},
            {"title": "B", "content": "Cb", "tags": ["y", "z"]},
        ]
        result = server.summarize_notes(query="test")
        assert "## A [tags: x]" in result
        assert "## B [tags: y, z]" in result
        assert "Summarize the following notes" in result

    @patch.object(redis_client, "list_notes")
    def test_default_query_is_empty(self, mock_list):
        mock_list.return_value = []
        server.summarize_notes()
        mock_list.assert_called_once_with(limit=50)
