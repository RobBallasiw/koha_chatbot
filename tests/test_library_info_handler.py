"""Tests for the library info handler module."""

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.library_info_handler import (
    CATEGORY_KEYWORDS,
    CONTACT_STAFF_MESSAGE,
    _match_category,
    _format_category_data,
    handle_library_info_query,
    load_library_info,
)
from app.models import LibraryInfo


SAMPLE_DATA = {
    "hours": {
        "monday": "9:00 AM - 8:00 PM",
        "tuesday": "9:00 AM - 8:00 PM",
        "saturday": "10:00 AM - 5:00 PM",
        "sunday": "Closed",
    },
    "policies": {
        "borrowing_limit": "15 items at a time",
        "renewal_rules": "Items may be renewed up to 2 times unless on hold",
        "membership": "Free for all residents with valid ID",
    },
    "fines": {
        "overdue_per_day": "$0.25 per day",
        "lost_item": "Replacement cost + $5.00 processing fee",
        "max_fine": "$10.00 per item",
    },
}


@pytest.fixture
def sample_library_info() -> LibraryInfo:
    return LibraryInfo(**SAMPLE_DATA)


@pytest.fixture
def sample_json_file(tmp_path):
    path = tmp_path / "library_info.json"
    path.write_text(json.dumps(SAMPLE_DATA), encoding="utf-8")
    return str(path)


@pytest.fixture
def mock_groq_client():
    client = MagicMock()
    client.chat.return_value = "The library is open Monday 9 AM to 8 PM."
    return client


# --- load_library_info tests ---


class TestLoadLibraryInfo:
    def test_loads_valid_file(self, sample_json_file):
        info = load_library_info(sample_json_file)
        assert isinstance(info, LibraryInfo)
        assert info.hours["monday"] == "9:00 AM - 8:00 PM"
        assert info.policies["borrowing_limit"] == "15 items at a time"
        assert info.fines["overdue_per_day"] == "$0.25 per day"

    def test_exits_on_file_not_found(self):
        with pytest.raises(SystemExit):
            load_library_info("/nonexistent/path/library_info.json")

    def test_exits_on_malformed_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not valid json {{{", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_library_info(str(path))

    def test_exits_on_invalid_structure(self, tmp_path):
        path = tmp_path / "incomplete.json"
        path.write_text(json.dumps({"hours": {}}), encoding="utf-8")
        with pytest.raises(SystemExit):
            load_library_info(str(path))


# --- _match_category tests ---


class TestMatchCategory:
    @pytest.mark.parametrize(
        "message,expected",
        [
            ("What are your hours?", "hours"),
            ("When do you open?", "hours"),
            ("What time do you close?", "hours"),
            ("What is the fine for overdue books?", "fines"),
            ("How much is the fee?", "fines"),
            ("What is the cost of a lost book?", "fines"),
            ("What is your borrowing policy?", "policies"),
            ("Can I renew my books?", "policies"),
            ("How do I get a membership?", "policies"),
        ],
    )
    def test_matches_correct_category(self, message, expected):
        assert _match_category(message) == expected

    def test_returns_none_for_unrelated_query(self):
        assert _match_category("Tell me a joke") is None

    def test_returns_none_for_empty_string(self):
        assert _match_category("") is None


# --- handle_library_info_query tests ---


class TestHandleLibraryInfoQuery:
    def test_returns_llm_response_for_hours_query(
        self, mock_groq_client, sample_library_info
    ):
        result = handle_library_info_query(
            mock_groq_client, "What are your hours?", sample_library_info, []
        )
        assert result == "The library is open Monday 9 AM to 8 PM."
        mock_groq_client.chat.assert_called_once()

    def test_returns_contact_staff_for_unmatched_query(
        self, mock_groq_client, sample_library_info
    ):
        result = handle_library_info_query(
            mock_groq_client, "Tell me a joke", sample_library_info, []
        )
        assert result == CONTACT_STAFF_MESSAGE
        mock_groq_client.chat.assert_not_called()

    def test_includes_conversation_history(
        self, mock_groq_client, sample_library_info
    ):
        history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello!"}]
        handle_library_info_query(
            mock_groq_client, "What are your hours?", sample_library_info, history
        )
        call_args = mock_groq_client.chat.call_args[0][0]
        # History should be included before the prompt message
        assert call_args[0] == history[0]
        assert call_args[1] == history[1]
        assert call_args[2]["role"] == "user"

    def test_prompt_contains_category_data(
        self, mock_groq_client, sample_library_info
    ):
        handle_library_info_query(
            mock_groq_client, "What is the overdue fine?", sample_library_info, []
        )
        call_args = mock_groq_client.chat.call_args[0][0]
        prompt_content = call_args[0]["content"]
        assert "overdue_per_day" in prompt_content
        assert "$0.25 per day" in prompt_content


# --- Hypothesis strategies ---

# Map each category to a keyword that will trigger it
_CATEGORY_TRIGGER = {
    "hours": "hours",
    "policies": "policy",
    "fines": "fine",
}


@st.composite
def library_info_strategy(draw):
    """Generate a LibraryInfo with random non-empty sections."""
    _val = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 ", min_size=1, max_size=30)

    def _section():
        n = draw(st.integers(min_value=1, max_value=4))
        keys = [draw(_val) for _ in range(n)]
        vals = [draw(_val) for _ in range(n)]
        return dict(zip(keys, vals))

    return LibraryInfo(hours=_section(), policies=_section(), fines=_section())


# --- Property-based tests ---


# Feature: library-ai-chatbot, Property 6: Library info retrieval returns relevant data
class TestLibraryInfoRetrievalProperty:
    """Property 6: For any category key (hours, policies, fines) present in the
    LibraryInfo store, querying the library info handler with a question about
    that category should produce a response containing at least one value from
    that category's data.

    Validates: Requirements 3.1, 3.2, 3.3
    """

    @given(
        category=st.sampled_from(["hours", "policies", "fines"]),
        library_info=library_info_strategy(),
    )
    @settings(max_examples=100)
    def test_handler_response_contains_category_data(self, category, library_info):
        """When the LLM echoes back the formatted data (mocked), the response
        must contain at least one value from the queried category."""
        section_data: dict[str, str] = getattr(library_info, category)
        formatted = _format_category_data(category, library_info)

        # Mock the Groq client to echo back the formatted data it receives,
        # simulating the LLM producing a response based on the provided info.
        client = MagicMock()
        client.chat.return_value = f"Here is the info: {formatted}"

        trigger_word = _CATEGORY_TRIGGER[category]
        message = f"Tell me about {trigger_word}"

        result = handle_library_info_query(client, message, library_info, [])

        # The response should contain at least one value from the category
        values = list(section_data.values())
        assert any(
            v in result for v in values
        ), f"Response did not contain any value from {category}: {values}"

    @given(
        category=st.sampled_from(["hours", "policies", "fines"]),
        library_info=library_info_strategy(),
    )
    @settings(max_examples=100)
    def test_matched_category_data_passed_to_llm(self, category, library_info):
        """The prompt sent to the LLM must include data from the matched
        category so the LLM can produce a relevant answer."""
        section_data: dict[str, str] = getattr(library_info, category)

        client = MagicMock()
        client.chat.return_value = "Some response"

        trigger_word = _CATEGORY_TRIGGER[category]
        message = f"What about {trigger_word}"

        handle_library_info_query(client, message, library_info, [])

        # Verify the LLM was called
        client.chat.assert_called_once()
        call_messages = client.chat.call_args[0][0]
        prompt_content = call_messages[-1]["content"]

        # The prompt must contain at least one value from the category section
        values = list(section_data.values())
        assert any(
            v in prompt_content for v in values
        ), f"Prompt did not contain any value from {category}"

    @given(library_info=library_info_strategy())
    @settings(max_examples=100)
    def test_unmatched_query_returns_contact_staff(self, library_info):
        """When no category keyword matches, the handler should return the
        contact-staff message without calling the LLM."""
        client = MagicMock()

        # Use a message that contains no category keywords
        result = handle_library_info_query(
            client, "xyzzy gibberish", library_info, []
        )

        assert result == CONTACT_STAFF_MESSAGE
        client.chat.assert_not_called()
