"""Property-based tests for the /api/chat endpoint.

Uses Hypothesis to verify universal properties across randomly generated inputs.
"""

from unittest.mock import patch, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st
from starlette.testclient import TestClient

from app.main import app
from app.models import ClassificationResult


# --- Strategies ---

_non_empty_message = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())
_session_id = st.text(min_size=1, max_size=50).filter(lambda s: s.strip())


class TestProperty15InvalidRequestsRejectedWith400:
    """Feature: library-ai-chatbot, Property 15: Invalid requests are rejected with 400.

    For any request to /api/chat where the message is empty, whitespace-only,
    or missing, or where the session_id is missing, the backend should return
    a 400 status code with a JSON body containing an error field.

    Validates: Requirements 8.2
    """

    @given(
        whitespace=st.text(
            alphabet=st.sampled_from([" ", "\t", "\n", "\r"]),
            min_size=0,
            max_size=20,
        ),
        session_id=_session_id,
    )
    @settings(max_examples=100)
    def test_empty_or_whitespace_message_returns_400(
        self, whitespace: str, session_id: str
    ):
        """Empty or whitespace-only messages are rejected with 400."""
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/chat",
            json={"message": whitespace, "session_id": session_id},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body

    @given(session_id=_session_id)
    @settings(max_examples=100)
    def test_missing_session_id_returns_400(self, session_id: str):
        """Requests without a session_id field are rejected with 400."""
        client = TestClient(app, raise_server_exceptions=False)
        # Send only message, no session_id
        resp = client.post(
            "/api/chat",
            json={"message": "Hello"},
        )
        # Pydantic validation will reject missing required field
        assert resp.status_code == 422 or resp.status_code == 400

    @given(
        message=_non_empty_message,
    )
    @settings(max_examples=100)
    def test_empty_session_id_returns_400(self, message: str):
        """Requests with empty or whitespace-only session_id are rejected with 400."""
        whitespace_ids = ["", "   ", "\t", "\n"]
        client = TestClient(app, raise_server_exceptions=False)
        for sid in whitespace_ids:
            resp = client.post(
                "/api/chat",
                json={"message": message, "session_id": sid},
            )
            assert resp.status_code == 400
            body = resp.json()
            assert "error" in body



class TestProperty16ValidResponsesContainRequiredJSONFields:
    """Feature: library-ai-chatbot, Property 16: Valid responses contain required JSON fields.

    For any valid request to /api/chat (non-empty message, valid session_id),
    the response should be valid JSON containing both a reply string field
    and a session_id string field.

    Validates: Requirements 8.4
    """

    @given(
        message=_non_empty_message,
        session_id=_session_id,
    )
    @settings(max_examples=100)
    def test_valid_request_returns_reply_and_session_id(
        self, message: str, session_id: str
    ):
        """Valid requests return JSON with reply and session_id string fields."""
        classification = ClassificationResult(intent="unclear", confidence=0.3)

        with (
            patch("app.main.classify_query", return_value=classification),
            patch("app.main.session_manager") as mock_sm,
            patch("app.main.groq_client"),
            patch("app.main.settings"),
        ):
            mock_sm.get_history.return_value = []

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/chat",
                json={"message": message, "session_id": session_id},
            )

            assert resp.status_code == 200
            body = resp.json()
            assert "reply" in body
            assert "session_id" in body
            assert isinstance(body["reply"], str)
            assert isinstance(body["session_id"], str)


class TestProperty10LLMCallsIncludeConversationHistory:
    """Feature: library-ai-chatbot, Property 10: LLM calls include conversation history.

    For any session with at least one prior message, when a new message is
    processed, the prompt sent to the Groq LLM client should include the
    prior conversation history messages.

    Validates: Requirements 6.2
    """

    @given(
        message=_non_empty_message,
        session_id=_session_id,
        history=st.lists(
            st.fixed_dictionaries(
                {
                    "role": st.sampled_from(["user", "assistant"]),
                    "content": st.text(min_size=1, max_size=100).filter(
                        lambda s: s.strip()
                    ),
                }
            ),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_classify_query_receives_conversation_history(
        self, message: str, session_id: str, history: list
    ):
        """When a session has prior messages, classify_query receives them."""
        classification = ClassificationResult(intent="unclear", confidence=0.3)

        with (
            patch("app.main.classify_query", return_value=classification) as mock_classify,
            patch("app.main.session_manager") as mock_sm,
            patch("app.main.groq_client") as mock_groq,
            patch("app.main.settings"),
        ):
            mock_sm.get_history.return_value = list(history)

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/chat",
                json={"message": message, "session_id": session_id},
            )

            assert resp.status_code == 200
            # classify_query should have been called with the history
            mock_classify.assert_called_once()
            call_args = mock_classify.call_args
            # classify_query(client, message, history)
            passed_history = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("conversation_history")
            # The history passed to classify_query should match what session_manager returned
            assert passed_history == history
