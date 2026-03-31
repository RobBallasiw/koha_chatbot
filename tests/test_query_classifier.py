"""Tests for the query classifier module."""

import json
from unittest.mock import MagicMock, patch

from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.models import ClassificationResult
from app.query_classifier import (
    CONFIDENCE_THRESHOLD,
    VALID_INTENTS,
    classify_query,
    _parse_classification,
)


def _make_client(response: str) -> MagicMock:
    """Return a mock GroqClient whose .chat() returns *response*."""
    client = MagicMock()
    client.chat.return_value = response
    return client


# --- classify_query integration with mock client ---


class TestClassifyQuery:
    def test_catalog_search_intent(self):
        payload = json.dumps({"intent": "catalog_search", "confidence": 0.95})
        client = _make_client(payload)
        result = classify_query(client, "Do you have any books by Toni Morrison?")
        assert result.intent == "catalog_search"
        assert result.confidence == 0.95

    def test_library_info_intent(self):
        payload = json.dumps({"intent": "library_info", "confidence": 0.88})
        client = _make_client(payload)
        result = classify_query(client, "What are your hours on Saturday?")
        assert result.intent == "library_info"
        assert result.confidence == 0.88

    def test_unclear_intent_explicit(self):
        payload = json.dumps({"intent": "unclear", "confidence": 0.3})
        client = _make_client(payload)
        result = classify_query(client, "hello")
        assert result.intent == "unclear"
        assert result.confidence == 0.3

    def test_low_confidence_forced_to_unclear(self):
        payload = json.dumps({"intent": "catalog_search", "confidence": 0.4})
        client = _make_client(payload)
        result = classify_query(client, "maybe books?")
        assert result.intent == "unclear"
        assert result.confidence == 0.4

    def test_conversation_history_included(self):
        payload = json.dumps({"intent": "catalog_search", "confidence": 0.9})
        client = _make_client(payload)
        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        classify_query(client, "Find me a book", conversation_history=history)
        call_args = client.chat.call_args[0][0]
        # History messages should precede the classification prompt.
        assert call_args[0] == history[0]
        assert call_args[1] == history[1]
        assert call_args[2]["role"] == "user"
        assert "Find me a book" in call_args[2]["content"]

    def test_no_history_sends_single_message(self):
        payload = json.dumps({"intent": "library_info", "confidence": 0.85})
        client = _make_client(payload)
        classify_query(client, "What are the fines?")
        call_args = client.chat.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0]["role"] == "user"


# --- _parse_classification unit tests ---


class TestParseClassification:
    def test_valid_catalog_search(self):
        raw = json.dumps({"intent": "catalog_search", "confidence": 0.92})
        result = _parse_classification(raw)
        assert result.intent == "catalog_search"
        assert result.confidence == 0.92

    def test_valid_library_info(self):
        raw = json.dumps({"intent": "library_info", "confidence": 0.8})
        result = _parse_classification(raw)
        assert result.intent == "library_info"
        assert result.confidence == 0.8

    def test_invalid_json_returns_unclear(self):
        result = _parse_classification("not json at all")
        assert result.intent == "unclear"
        assert result.confidence == 0.0

    def test_missing_intent_key(self):
        raw = json.dumps({"confidence": 0.9})
        result = _parse_classification(raw)
        # Missing intent defaults to "unclear", confidence 0.9 >= threshold
        # but "unclear" is a valid intent so stays "unclear"
        assert result.intent == "unclear"

    def test_invalid_intent_value(self):
        raw = json.dumps({"intent": "something_else", "confidence": 0.99})
        result = _parse_classification(raw)
        assert result.intent == "unclear"
        assert result.confidence == 0.0

    def test_confidence_clamped_above_one(self):
        raw = json.dumps({"intent": "catalog_search", "confidence": 1.5})
        result = _parse_classification(raw)
        assert result.confidence == 1.0
        assert result.intent == "catalog_search"

    def test_confidence_clamped_below_zero(self):
        raw = json.dumps({"intent": "catalog_search", "confidence": -0.5})
        result = _parse_classification(raw)
        assert result.confidence == 0.0
        # Negative confidence is below threshold → forced to unclear
        assert result.intent == "unclear"

    def test_confidence_at_threshold_is_unclear(self):
        raw = json.dumps({"intent": "catalog_search", "confidence": 0.59})
        result = _parse_classification(raw)
        assert result.intent == "unclear"

    def test_confidence_at_threshold_boundary(self):
        raw = json.dumps({"intent": "catalog_search", "confidence": 0.6})
        result = _parse_classification(raw)
        assert result.intent == "catalog_search"

    def test_empty_string_returns_unclear(self):
        result = _parse_classification("")
        assert result.intent == "unclear"
        assert result.confidence == 0.0

    def test_json_with_extra_text(self):
        # LLM sometimes wraps JSON in extra text
        result = _parse_classification('Here is the result: {"intent": "catalog_search"}')
        assert result.intent == "unclear"
        assert result.confidence == 0.0


# --- Property-Based Tests (hypothesis) ---

# Strategies
_non_empty_text = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())
_valid_intent = st.sampled_from(sorted(VALID_INTENTS))
_confidence = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


class TestProperty7QueryClassificationReturnsValidResult:
    """Feature: library-ai-chatbot, Property 7: Query classification returns valid result.

    For any non-empty patron message string, the query classifier should return
    a ClassificationResult with intent in {"catalog_search", "library_info", "unclear"}
    and confidence between 0.0 and 1.0 inclusive.

    Validates: Requirements 4.1
    """

    @given(
        message=_non_empty_text,
        intent=_valid_intent,
        confidence=_confidence,
    )
    @hyp_settings(max_examples=100)
    def test_classification_always_returns_valid_result(
        self, message: str, intent: str, confidence: float
    ):
        """Regardless of the LLM response content, classify_query always
        returns a ClassificationResult with a valid intent and bounded confidence."""
        payload = json.dumps({"intent": intent, "confidence": confidence})
        client = _make_client(payload)

        result = classify_query(client, message)

        assert isinstance(result, ClassificationResult)
        assert result.intent in VALID_INTENTS
        assert 0.0 <= result.confidence <= 1.0

    @given(message=_non_empty_text)
    @hyp_settings(max_examples=100)
    def test_classification_valid_on_malformed_llm_response(self, message: str):
        """Even when the LLM returns garbage, the result is still valid."""
        client = _make_client("this is not json")

        result = classify_query(client, message)

        assert isinstance(result, ClassificationResult)
        assert result.intent in VALID_INTENTS
        assert 0.0 <= result.confidence <= 1.0

    @given(
        message=_non_empty_text,
        intent=st.text(min_size=1, max_size=50).filter(
            lambda s: s not in VALID_INTENTS
        ),
        confidence=_confidence,
    )
    @hyp_settings(max_examples=100)
    def test_classification_valid_on_unknown_intent(
        self, message: str, intent: str, confidence: float
    ):
        """Unknown intent values from the LLM still produce a valid result."""
        payload = json.dumps({"intent": intent, "confidence": confidence})
        client = _make_client(payload)

        result = classify_query(client, message)

        assert isinstance(result, ClassificationResult)
        assert result.intent in VALID_INTENTS
        assert 0.0 <= result.confidence <= 1.0


class TestProperty8RoutingMatchesClassificationIntent:
    """Feature: library-ai-chatbot, Property 8: Routing matches classification intent.

    For any ClassificationResult with intent "catalog_search" or "library_info",
    the backend should invoke the handler corresponding to that intent.

    Validates: Requirements 4.2, 4.3
    """

    @given(
        message=_non_empty_text,
        confidence=st.floats(
            min_value=CONFIDENCE_THRESHOLD, max_value=1.0, allow_nan=False
        ),
    )
    @hyp_settings(max_examples=100)
    def test_catalog_search_routes_to_catalog_handler(
        self, message: str, confidence: float
    ):
        """When classify_query returns catalog_search, the chat endpoint
        invokes handle_catalog_query."""
        classification = ClassificationResult(
            intent="catalog_search", confidence=confidence
        )

        with (
            patch("app.main.classify_query", return_value=classification),
            patch(
                "app.main.handle_catalog_query", return_value="catalog result"
            ) as mock_catalog,
            patch("app.main.handle_library_info_query") as mock_info,
            patch("app.main.session_manager") as mock_sm,
            patch("app.main.groq_client"),
            patch("app.main.settings"),
        ):
            mock_sm.get_history.return_value = []

            from starlette.testclient import TestClient
            from app.main import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/chat",
                json={"message": message, "session_id": "test-session"},
            )

            assert resp.status_code == 200
            mock_catalog.assert_called_once()
            mock_info.assert_not_called()

    @given(
        message=_non_empty_text,
        confidence=st.floats(
            min_value=CONFIDENCE_THRESHOLD, max_value=1.0, allow_nan=False
        ),
    )
    @hyp_settings(max_examples=100)
    def test_library_info_routes_to_info_handler(
        self, message: str, confidence: float
    ):
        """When classify_query returns library_info, the chat endpoint
        invokes handle_library_info_query."""
        classification = ClassificationResult(
            intent="library_info", confidence=confidence
        )

        with (
            patch("app.main.classify_query", return_value=classification),
            patch("app.main.handle_catalog_query") as mock_catalog,
            patch(
                "app.main.handle_library_info_query",
                return_value="info result",
            ) as mock_info,
            patch("app.main.session_manager") as mock_sm,
            patch("app.main.groq_client"),
            patch("app.main.settings"),
            patch("app.main.library_info"),
        ):
            mock_sm.get_history.return_value = []

            from starlette.testclient import TestClient
            from app.main import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/chat",
                json={"message": message, "session_id": "test-session"},
            )

            assert resp.status_code == 200
            mock_info.assert_called_once()
            mock_catalog.assert_not_called()

    @given(message=_non_empty_text)
    @hyp_settings(max_examples=100)
    def test_unclear_intent_returns_clarifying_message(self, message: str):
        """When classify_query returns unclear, the response is the
        clarifying message (neither handler is called)."""
        classification = ClassificationResult(intent="unclear", confidence=0.3)

        with (
            patch("app.main.classify_query", return_value=classification),
            patch("app.main.handle_catalog_query") as mock_catalog,
            patch("app.main.handle_library_info_query") as mock_info,
            patch("app.main.session_manager") as mock_sm,
            patch("app.main.groq_client"),
            patch("app.main.settings"),
        ):
            mock_sm.get_history.return_value = []

            from starlette.testclient import TestClient
            from app.main import app, CLARIFYING_MESSAGE

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/chat",
                json={"message": message, "session_id": "test-session"},
            )

            assert resp.status_code == 200
            assert resp.json()["reply"] == CLARIFYING_MESSAGE
            mock_catalog.assert_not_called()
            mock_info.assert_not_called()
