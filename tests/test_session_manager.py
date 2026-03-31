"""Property-based tests for the session manager.

Uses Hypothesis to verify universal properties across randomly generated inputs.
"""

import uuid

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.session_manager import SessionManager, MAX_MESSAGES


# --- Strategies ---

roles = st.sampled_from(["user", "assistant"])
message_content = st.text(min_size=1, max_size=200)
session_ids = st.text(min_size=1, max_size=50).filter(lambda s: s.strip() != "")


# Feature: library-ai-chatbot, Property 9: Session stores all messages
@given(messages=st.lists(st.tuples(roles, message_content), min_size=1, max_size=20))
@settings(max_examples=100)
def test_session_stores_all_messages(messages):
    """All messages added to a session are stored in order (up to the cap)."""
    mgr = SessionManager()
    sid = str(uuid.uuid4())

    for role, content in messages:
        mgr.add_message(sid, role, content)

    history = mgr.get_history(sid)

    assert len(history) == len(messages)
    for stored, (role, content) in zip(history, messages):
        assert stored["role"] == role
        assert stored["content"] == content


# Feature: library-ai-chatbot, Property 11: Session history capped at 20 messages
@given(
    messages=st.lists(
        st.tuples(roles, message_content),
        min_size=MAX_MESSAGES + 1,
        max_size=MAX_MESSAGES + 40,
    )
)
@settings(max_examples=100)
def test_session_history_capped_at_max(messages):
    """No matter how many messages are added, history never exceeds MAX_MESSAGES.

    When the cap is exceeded the oldest messages are dropped.
    """
    mgr = SessionManager()
    sid = str(uuid.uuid4())

    for role, content in messages:
        mgr.add_message(sid, role, content)

    history = mgr.get_history(sid)

    assert len(history) <= MAX_MESSAGES

    # The retained messages should be the *last* MAX_MESSAGES entries.
    expected = messages[-MAX_MESSAGES:]
    for stored, (role, content) in zip(history, expected):
        assert stored["role"] == role
        assert stored["content"] == content


# Feature: library-ai-chatbot, Property 12: New sessions start with empty history
@given(sid=session_ids)
@settings(max_examples=100)
def test_new_sessions_start_with_empty_history(sid):
    """A brand-new session ID always returns an empty message list."""
    mgr = SessionManager()
    history = mgr.get_history(sid)
    assert history == []
