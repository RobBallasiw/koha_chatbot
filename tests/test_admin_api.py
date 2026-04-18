"""Property-based tests for admin API endpoints.

Tests Properties 4, 5, 6, 8, and 9 from the admin-chat-monitoring design.
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
statuses = st.sampled_from(["active", "expired"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> SessionStore:
    """Return a SessionStore backed by a fresh temp-file SQLite database."""
    fd, db_file = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return SessionStore(db_path=db_file)



# ---------------------------------------------------------------------------
# Property 4: Session metadata completeness
# Feature: admin-chat-monitoring, Property 4: Session metadata completeness
# ---------------------------------------------------------------------------
# **Validates: Requirements 2.2, 3.4**


@given(
    session_id=session_ids,
    messages=st.lists(
        st.tuples(roles, contents),
        min_size=1,
        max_size=10,
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_session_metadata_completeness_list(session_id, messages):
    """Sessions in the list endpoint contain all required metadata fields."""
    store = _make_store()
    set_session_store(store)

    base_ts = 1_000_000.0
    for idx, (role, content) in enumerate(messages):
        store.save_message(session_id, role, content, timestamp=base_ts + idx)

    with patch("app.admin_auth.get_admin_api_key", return_value=TEST_ADMIN_KEY):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            resp = await client.get("/admin/api/sessions", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    for session in data["sessions"]:
        # session_id: non-empty string
        assert isinstance(session["session_id"], str)
        assert len(session["session_id"]) > 0
        # created_at: positive number
        assert isinstance(session["created_at"], (int, float))
        assert session["created_at"] > 0
        # last_activity: positive number
        assert isinstance(session["last_activity"], (int, float))
        assert session["last_activity"] > 0
        # message_count: non-negative integer
        assert isinstance(session["message_count"], int)
        assert session["message_count"] >= 0
        # status: "active" or "expired"
        assert session["status"] in {"active", "expired"}


@given(
    session_id=session_ids,
    messages=st.lists(
        st.tuples(roles, contents),
        min_size=1,
        max_size=10,
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_session_metadata_completeness_detail(session_id, messages):
    """Session detail endpoint contains all required metadata fields."""
    store = _make_store()
    set_session_store(store)

    base_ts = 1_000_000.0
    for idx, (role, content) in enumerate(messages):
        store.save_message(session_id, role, content, timestamp=base_ts + idx)

    with patch("app.admin_auth.get_admin_api_key", return_value=TEST_ADMIN_KEY):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            resp = await client.get(
                f"/admin/api/sessions/{session_id}", headers=HEADERS
            )

    assert resp.status_code == 200
    session = resp.json()
    assert isinstance(session["session_id"], str)
    assert len(session["session_id"]) > 0
    assert isinstance(session["created_at"], (int, float))
    assert session["created_at"] > 0
    assert isinstance(session["last_activity"], (int, float))
    assert session["last_activity"] > 0
    assert isinstance(session["message_count"], int)
    assert session["message_count"] >= 0
    assert session["status"] in {"active", "expired"}


# ---------------------------------------------------------------------------
# Property 5: Status filter correctness
# Feature: admin-chat-monitoring, Property 5: Status filter correctness
# ---------------------------------------------------------------------------
# **Validates: Requirements 2.4, 3.3**


@given(
    data=st.lists(
        st.tuples(session_ids, timestamps),
        min_size=1,
        max_size=10,
    ),
    filter_status=statuses,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_status_filter_correctness(data, filter_status):
    """Filtered session list only contains sessions matching the requested status."""
    store = _make_store()
    set_session_store(store)

    for sid, ts in data:
        store.save_message(sid, "user", "hello", timestamp=ts)

    with patch("app.admin_auth.get_admin_api_key", return_value=TEST_ADMIN_KEY):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            resp = await client.get(
                "/admin/api/sessions",
                params={"status": filter_status, "page_size": 100},
                headers=HEADERS,
            )

    assert resp.status_code == 200
    data_resp = resp.json()
    for session in data_resp["sessions"]:
        assert session["status"] == filter_status


# ---------------------------------------------------------------------------
# Property 6: Keyword search returns matching sessions
# Feature: admin-chat-monitoring, Property 6: Keyword search returns matching sessions
# ---------------------------------------------------------------------------
# **Validates: Requirements 2.5**


@given(
    data=st.lists(
        st.tuples(
            session_ids,
            st.lists(contents, min_size=1, max_size=5),
        ),
        min_size=1,
        max_size=8,
    ),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_keyword_search_returns_matching_sessions(data):
    """Search results only contain sessions with at least one message matching the keyword."""
    store = _make_store()
    set_session_store(store)

    # Deduplicate session IDs — keep the first occurrence
    seen_sids: set[str] = set()
    unique_data: list[tuple[str, list[str]]] = []
    for sid, msg_list in data:
        if sid not in seen_sids:
            seen_sids.add(sid)
            unique_data.append((sid, msg_list))

    # Populate the store
    base_ts = 1_000_000.0
    all_messages: dict[str, list[str]] = {}
    for sid, msg_list in unique_data:
        all_messages[sid] = msg_list
        for i, content in enumerate(msg_list):
            store.save_message(sid, "user", content, timestamp=base_ts + i)

    # Pick a keyword from the first session's first message (guaranteed to exist)
    first_sid, first_msgs = unique_data[0]
    # Use a substring of the first message as the keyword
    keyword = first_msgs[0][:10]  # first 10 chars
    if not keyword.strip():
        return  # skip if keyword is whitespace-only

    with patch("app.admin_auth.get_admin_api_key", return_value=TEST_ADMIN_KEY):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            resp = await client.get(
                "/admin/api/sessions",
                params={"search": keyword, "page_size": 100},
                headers=HEADERS,
            )

    assert resp.status_code == 200
    result = resp.json()

    # Every returned session must contain at least one message with the keyword
    returned_sids = {s["session_id"] for s in result["sessions"]}
    for sid in returned_sids:
        session_msgs = all_messages.get(sid, [])
        assert any(
            keyword in msg for msg in session_msgs
        ), f"Session {sid} returned by search but no message contains '{keyword}'"


# ---------------------------------------------------------------------------
# Property 8: Pagination respects page size
# Feature: admin-chat-monitoring, Property 8: Pagination respects page size
# ---------------------------------------------------------------------------
# **Validates: Requirements 4.2**


@given(
    num_sessions=st.integers(min_value=1, max_value=20),
    page=st.integers(min_value=1, max_value=5),
    page_size=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_pagination_respects_page_size(num_sessions, page, page_size):
    """Response contains at most page_size sessions and total reflects actual count."""
    store = _make_store()
    set_session_store(store)

    # Create distinct sessions
    base_ts = 1_000_000.0
    for i in range(num_sessions):
        store.save_message(f"sess{i}", "user", "hello", timestamp=base_ts + i)

    with patch("app.admin_auth.get_admin_api_key", return_value=TEST_ADMIN_KEY):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            resp = await client.get(
                "/admin/api/sessions",
                params={"page": page, "page_size": page_size},
                headers=HEADERS,
            )

    assert resp.status_code == 200
    data = resp.json()

    # At most page_size sessions returned
    assert len(data["sessions"]) <= page_size
    # Total reflects the actual number of sessions in the store
    assert data["total"] == num_sessions


# ---------------------------------------------------------------------------
# Property 9: Non-existent session returns 404
# Feature: admin-chat-monitoring, Property 9: Non-existent session returns 404
# ---------------------------------------------------------------------------
# **Validates: Requirements 4.4**


@given(
    session_id=st.text(
        min_size=1,
        max_size=50,
        alphabet=st.characters(whitelist_categories=("L", "N")),
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_nonexistent_session_returns_404(session_id):
    """Requesting a session ID that doesn't exist returns 404 with error field."""
    store = _make_store()
    set_session_store(store)

    # Store is empty — any session_id is non-existent
    with patch("app.admin_auth.get_admin_api_key", return_value=TEST_ADMIN_KEY):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            resp = await client.get(
                f"/admin/api/sessions/{session_id}", headers=HEADERS
            )

    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
