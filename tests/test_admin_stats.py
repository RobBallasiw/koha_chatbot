"""Property-based tests for admin statistics endpoint.

Tests Property 11 from the admin-chat-monitoring design.
"""

import os
import tempfile
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.admin_routes import set_session_store
from app.main import app
from app.session_store import SessionStore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_ADMIN_KEY = "test-admin-key-12345"
BASE_URL = "http://testserver"
HEADERS = {"X-Admin-Key": TEST_ADMIN_KEY}

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

roles = st.sampled_from(["user", "assistant"])
contents = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
)
session_ids = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("L", "N")),
)
timestamps = st.floats(
    min_value=1.0, max_value=2_000_000_000.0, allow_nan=False, allow_infinity=False
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> SessionStore:
    """Return a SessionStore backed by a fresh temp-file SQLite database."""
    fd, db_file = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return SessionStore(db_path=db_file)


# ---------------------------------------------------------------------------
# Property 11: Statistics accuracy
# Feature: admin-chat-monitoring, Property 11: Statistics accuracy
# ---------------------------------------------------------------------------
# **Validates: Requirements 6.1, 6.2**


@given(
    data=st.lists(
        st.tuples(
            session_ids,
            st.lists(st.tuples(roles, contents), min_size=1, max_size=5),
        ),
        min_size=0,
        max_size=8,
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_statistics_accuracy(data):
    """Stats endpoint totals match actual session/message counts."""
    store = _make_store()
    set_session_store(store)

    # Deduplicate session IDs — keep the first occurrence
    seen_sids: set[str] = set()
    unique_data: list[tuple[str, list[tuple[str, str]]]] = []
    for sid, msg_list in data:
        if sid not in seen_sids:
            seen_sids.add(sid)
            unique_data.append((sid, msg_list))

    # Populate the store and track expected counts
    base_ts = 1_000_000.0
    expected_total_messages = 0
    for sid, msg_list in unique_data:
        for i, (role, content) in enumerate(msg_list):
            store.save_message(sid, role, content, timestamp=base_ts + i)
            expected_total_messages += 1

    expected_total_sessions = len(unique_data)

    with patch("app.admin_auth.get_admin_api_key", return_value=TEST_ADMIN_KEY):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            resp = await client.get("/admin/api/stats", headers=HEADERS)

    assert resp.status_code == 200
    stats = resp.json()

    # total_sessions == number of distinct sessions
    assert stats["total_sessions"] == expected_total_sessions
    # total_messages == sum of all messages across all sessions
    assert stats["total_messages"] == expected_total_messages
    # active_sessions + expired_sessions == total_sessions
    assert stats["active_sessions"] + stats["expired_sessions"] == stats["total_sessions"]
