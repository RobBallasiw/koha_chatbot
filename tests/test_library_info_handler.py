"""Tests for the library info handler module."""

import json
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.library_info_handler import (
    CONTACT_STAFF_MESSAGE,
    _classify_category,
    _format_category_data,
    handle_library_info_query,
    load_library_info,
)
from app.models import LibraryInfo


SAMPLE_DATA = {
    "locations": {
        "Main": {
            "address": "123 Main St",
            "hours": {
                "monday": "9:00 AM - 8:00 PM",
                "saturday": "10:00 AM - 5:00 PM",
                "sunday": "Closed",
            },
        }
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
    client.chat_with_system.return_value = '{"category": "hours"}'
    return client


# --- load_library_info tests ---


class TestLoadLibraryInfo:
    def test_loads_valid_file(self, sample_json_file):
        info = load_library_info(sample_json_file)
        assert isinstance(info, LibraryInfo)
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
        path.write_text(json.dumps({"locations": "not_a_dict"}), encoding="utf-8")
        with pytest.raises(SystemExit):
            load_library_info(str(path))


# --- _classify_category tests ---


class TestClassifyCategory:
    def test_returns_hours(self):
        client = MagicMock()
        client.chat_with_system.return_value = '{"category": "hours"}'
        assert _classify_category(client, "What are your hours?") == "hours"

    def test_returns_fines(self):
        client = MagicMock()
        client.chat_with_system.return_value = '{"category": "fines"}'
        assert _classify_category(client, "overdue fine?") == "fines"

    def test_returns_policies(self):
        client = MagicMock()
        client.chat_with_system.return_value = '{"category": "policies"}'
        assert _classify_category(client, "borrowing limit?") == "policies"

    def test_returns_all(self):
        client = MagicMock()
        client.chat_with_system.return_value = '{"category": "all"}'
        assert _classify_category(client, "tell me everything") == "all"

    def test_returns_none_for_unrelated(self):
        client = MagicMock()
        client.chat_with_system.return_value = '{"category": "none"}'
        assert _classify_category(client, "tell me a joke") is None

    def test_returns_none_on_parse_failure(self):
        client = MagicMock()
        client.chat_with_system.return_value = "not json"
        assert _classify_category(client, "hello") is None


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

    def test_returns_contact_staff_for_none_category(
        self, mock_groq_client, sample_library_info
    ):
        mock_groq_client.chat_with_system.return_value = '{"category": "none"}'
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
        assert call_args[0] == history[0]
        assert call_args[1] == history[1]

    def test_all_category_includes_all_data(
        self, mock_groq_client, sample_library_info
    ):
        mock_groq_client.chat_with_system.return_value = '{"category": "all"}'
        handle_library_info_query(
            mock_groq_client, "Tell me everything about the library", sample_library_info, []
        )
        call_args = mock_groq_client.chat.call_args[0][0]
        prompt = call_args[-1]["content"]
        assert "borrowing_limit" in prompt
        assert "overdue_per_day" in prompt
        assert "monday" in prompt


# --- Property-based tests ---


@st.composite
def library_info_strategy(draw):
    _val = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 ", min_size=1, max_size=30)

    def _section():
        n = draw(st.integers(min_value=1, max_value=4))
        keys = [draw(_val) for _ in range(n)]
        vals = [draw(_val) for _ in range(n)]
        return dict(zip(keys, vals))

    return LibraryInfo(policies=_section(), fines=_section())


class TestLibraryInfoRetrievalProperty:
    @given(
        category=st.sampled_from(["policies", "fines"]),
        library_info=library_info_strategy(),
    )
    @settings(max_examples=50)
    def test_handler_response_contains_category_data(self, category, library_info):
        section_data: dict[str, str] = getattr(library_info, category)
        formatted = _format_category_data(category, library_info)

        client = MagicMock()
        client.chat_with_system.return_value = json.dumps({"category": category})
        client.chat.return_value = f"Here is the info: {formatted}"

        result = handle_library_info_query(client, f"Tell me about {category}", library_info, [])
        values = list(section_data.values())
        assert any(v in result for v in values)

    @given(library_info=library_info_strategy())
    @settings(max_examples=50)
    def test_unmatched_query_returns_contact_staff(self, library_info):
        client = MagicMock()
        client.chat_with_system.return_value = '{"category": "none"}'

        result = handle_library_info_query(client, "xyzzy gibberish", library_info, [])
        assert result == CONTACT_STAFF_MESSAGE
        client.chat.assert_not_called()
