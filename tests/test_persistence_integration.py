"""Unit tests for persistence integration (Task 5.3).

Test 1: Chat works when DB is unavailable (Req 1.5)
Test 2: Persistence survives in-memory cleanup (Req 1.3)
"""

import os
import tempfile
import time
from unittest.mock import patch, MagicMock

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models import ClassificationResult
from app.session_manager import SessionManager, SESSION_TIMEOUT
from app.session_store import SessionStore


class TestChatWorksWhenDBUnavailable:
    """Verify the chat endpoint returns a valid response even when the
    SessionStore raises an exception (Req 1.5: graceful degradation)."""

    def test_chat_returns_200_when_session_store_save_raises(self):
        """If session_store.save_message raises, the patron still gets a 200
        response with a valid ChatResponse containing reply and session_id."""
        classification = ClassificationResult(intent="unclear", confidence=0.3)

        # Create a mock session_store whose save_message always explodes
        broken_store = MagicMock()
        broken_store.save_message.side_effect = Exception("DB is on fire")

        with (
            patch("app.main.classify_query", return_value=classification),
            patch("app.main.session_manager") as mock_sm,
            patch("app.main.groq_client"),
            patch("app.main.settings"),
            patch("app.main.session_store", broken_store),
        ):
            mock_sm.get_history.return_value = []

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/chat",
                json={"message": "Hello there", "session_id": "test-session-1"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "reply" in body
        assert isinstance(body["reply"], str)
        assert body["session_id"] == "test-session-1"

    def test_chat_returns_200_when_session_store_is_none(self):
        """If session_store is None (never initialised), the patron still
        gets a valid response — no persistence attempted at all."""
        classification = ClassificationResult(intent="greeting", confidence=0.9)

        with (
            patch("app.main.classify_query", return_value=classification),
            patch("app.main.session_manager") as mock_sm,
            patch("app.main.groq_client"),
            patch("app.main.settings"),
            patch("app.main.session_store", None),
        ):
            mock_sm.get_history.return_value = []

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/chat",
                json={"message": "Hi!", "session_id": "test-session-2"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "reply" in body
        assert body["session_id"] == "test-session-2"


class TestPersistenceSurvivesInMemoryCleanup:
    """Verify that messages persisted to the SessionStore survive when the
    in-memory SessionManager cleans up expired sessions (Req 1.3)."""

    def test_session_store_retains_messages_after_session_manager_cleanup(self):
        """Save messages to both SessionManager and SessionStore, expire the
        in-memory session, run cleanup, then confirm the SessionStore still
        has the messages."""
        # Set up a real SessionStore backed by a temp file
        fd, db_file = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        store = SessionStore(db_path=db_file)

        # Set up a real SessionManager
        mgr = SessionManager()

        session_id = "persist-test-session"

        # Simulate a conversation: add to both stores
        mgr.add_message(session_id, "user", "Do you have any Python books?")
        mgr.add_message(session_id, "assistant", "Yes, we have several!")
        store.save_message(session_id, "user", "Do you have any Python books?")
        store.save_message(session_id, "assistant", "Yes, we have several!")

        # Force the in-memory session to be expired
        session_data = mgr.get_or_create_session(session_id)
        session_data.last_accessed = time.time() - SESSION_TIMEOUT - 1

        # Run cleanup — this removes the session from memory
        mgr.cleanup_expired()

        # In-memory history should now be empty (new session created on access)
        history = mgr.get_history(session_id)
        assert history == []

        # SessionStore should still have both messages
        detail = store.get_session(session_id)
        assert detail is not None
        assert len(detail.messages) == 2
        assert detail.messages[0].role == "user"
        assert detail.messages[0].content == "Do you have any Python books?"
        assert detail.messages[1].role == "assistant"
        assert detail.messages[1].content == "Yes, we have several!"

        # Cleanup temp file
        os.unlink(db_file)
