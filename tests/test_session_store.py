"""Property-based tests for SessionStore.

Tests Properties 1, 2, 3, and 7 from the admin-chat-monitoring design.
"""

import os
import tempfile

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.session_store import SessionStore


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


def _make_store() -> SessionStore:
    """Return a SessionStore backed by a fresh temp-file SQLite database."""
    fd, db_file = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return SessionStore(db_path=db_file)


# ---------------------------------------------------------------------------
# Property 1: Message persistence round-trip
# Feature: admin-chat-monitoring, Property 1: Message persistence round-trip
# ---------------------------------------------------------------------------
# **Validates: Requirements 1.1, 4.3**


@given(
    session_id=session_ids,
    messages=st.lists(
        st.tuples(roles, contents),
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=100)
def test_message_persistence_round_trip(session_id, messages):
    """Save messages then retrieve — verify order and content match."""
    store = _make_store()

    # Use increasing timestamps so ordering is deterministic
    base_ts = 1_000_000.0
    for idx, (role, content) in enumerate(messages):
        store.save_message(session_id, role, content, timestamp=base_ts + idx)

    detail = store.get_session(session_id)
    assert detail is not None
    assert len(detail.messages) == len(messages)

    for saved, (expected_role, expected_content) in zip(detail.messages, messages):
        assert saved.role == expected_role
        assert saved.content == expected_content


# ---------------------------------------------------------------------------
# Property 2: Persisted message structure invariant
# Feature: admin-chat-monitoring, Property 2: Persisted message structure invariant
# ---------------------------------------------------------------------------
# **Validates: Requirements 1.2, 1.4**


@given(
    session_id=session_ids,
    messages=st.lists(
        st.tuples(roles, contents, timestamps),
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=100)
def test_persisted_message_structure_invariant(session_id, messages):
    """Verify role, content, and timestamp on all saved messages."""
    store = _make_store()

    for role, content, ts in messages:
        store.save_message(session_id, role, content, timestamp=ts)

    detail = store.get_session(session_id)
    assert detail is not None

    for msg in detail.messages:
        assert msg.role in {"user", "assistant"}
        assert len(msg.content) > 0
        assert msg.timestamp > 0


# ---------------------------------------------------------------------------
# Property 3: Session list ordered by most recent activity
# Feature: admin-chat-monitoring, Property 3: Session list ordered by most recent activity
# ---------------------------------------------------------------------------
# **Validates: Requirements 2.1**


@given(
    data=st.lists(
        st.tuples(session_ids, timestamps),
        min_size=1,
        max_size=15,
    ),
)
@settings(max_examples=100)
def test_session_list_ordered_by_most_recent_activity(data):
    """Verify descending last_activity order in session list."""
    store = _make_store()

    # Deduplicate session IDs — keep the last occurrence so each session
    # has a single deterministic last_activity.
    seen: dict[str, float] = {}
    for sid, ts in data:
        seen[sid] = ts  # last write wins for last_activity

    for sid, ts in data:
        store.save_message(sid, "user", "hello", timestamp=ts)

    result = store.get_sessions(page=1, page_size=len(seen) + 1)

    activities = [s.last_activity for s in result.sessions]
    # Should be in descending order
    for i in range(len(activities) - 1):
        assert activities[i] >= activities[i + 1]


# ---------------------------------------------------------------------------
# Property 7: Messages in chronological order
# Feature: admin-chat-monitoring, Property 7: Messages in chronological order
# ---------------------------------------------------------------------------
# **Validates: Requirements 3.1**


@given(
    session_id=session_ids,
    ts_list=st.lists(
        timestamps,
        min_size=2,
        max_size=20,
    ),
)
@settings(max_examples=100)
def test_messages_in_chronological_order(session_id, ts_list):
    """Verify ascending timestamp order in detail response."""
    store = _make_store()

    sorted_ts = sorted(ts_list)
    for ts in sorted_ts:
        store.save_message(session_id, "user", "msg", timestamp=ts)

    detail = store.get_session(session_id)
    assert detail is not None

    msg_timestamps = [m.timestamp for m in detail.messages]
    for i in range(len(msg_timestamps) - 1):
        assert msg_timestamps[i] <= msg_timestamps[i + 1]
