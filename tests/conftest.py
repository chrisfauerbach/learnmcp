from unittest.mock import MagicMock, patch

import pytest

from knowledge_base import redis_client as rc


@pytest.fixture(autouse=True)
def reset_client():
    """Reset the module-level singleton before and after each test."""
    rc._client = None
    yield
    rc._client = None


@pytest.fixture
def mock_redis():
    """Patch get_client() to return a MagicMock and ensure_index() to a no-op."""
    mock = MagicMock()
    with (
        patch.object(rc, "get_client", return_value=mock),
        patch.object(rc, "ensure_index"),
    ):
        yield mock


@pytest.fixture
def mock_ft(mock_redis):
    """Convenience accessor for the FT (search) interface on mock_redis."""
    return mock_redis.ft.return_value


