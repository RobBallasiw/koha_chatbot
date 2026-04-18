"""Tests for the LLM client module (Ollama via OpenAI-compatible API)."""

from unittest.mock import MagicMock, patch

import pytest
from openai import APIError, APITimeoutError

from app.groq_client import (
    GroqClient,
    SYSTEM_PROMPT,
    DEFAULT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    FALLBACK_GENERAL,
)


@pytest.fixture
def mock_openai():
    """Patch the OpenAI constructor and return the mock client instance."""
    with patch("app.groq_client.OpenAI") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _make_completion(content: str) -> MagicMock:
    """Build a fake chat completion response."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# --- Constructor defaults ---

def test_default_parameters():
    """Constructor uses correct defaults for model, max_tokens, temperature."""
    with patch("app.groq_client.OpenAI"):
        client = GroqClient()
    assert client.model == DEFAULT_MODEL
    assert client.max_tokens == DEFAULT_MAX_TOKENS
    assert client.temperature == DEFAULT_TEMPERATURE


def test_custom_parameters():
    """Constructor accepts custom model, max_tokens, temperature."""
    with patch("app.groq_client.OpenAI"):
        client = GroqClient(
            model="custom-model",
            max_tokens=512,
            temperature=0.3,
        )
    assert client.model == "custom-model"
    assert client.max_tokens == 512
    assert client.temperature == 0.3


# --- System prompt inclusion ---

def test_system_prompt_prepended(mock_openai):
    """The system prompt is always the first message sent to the API."""
    mock_openai.chat.completions.create.return_value = _make_completion("hi")
    client = GroqClient()

    client.chat([{"role": "user", "content": "hello"}])

    call_kwargs = mock_openai.chat.completions.create.call_args
    sent_messages = call_kwargs.kwargs["messages"]
    assert sent_messages[0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_system_prompt_with_empty_history(mock_openai):
    """System prompt is included even when conversation history is empty."""
    mock_openai.chat.completions.create.return_value = _make_completion("hi")
    client = GroqClient()

    client.chat([])

    sent_messages = mock_openai.chat.completions.create.call_args.kwargs["messages"]
    assert len(sent_messages) == 1
    assert sent_messages[0]["role"] == "system"


# --- Successful chat ---

def test_chat_returns_assistant_content(mock_openai):
    """chat() returns the content string from the first choice."""
    mock_openai.chat.completions.create.return_value = _make_completion(
        "The library opens at 9 AM."
    )
    client = GroqClient()

    result = client.chat([{"role": "user", "content": "When do you open?"}])

    assert result == "The library opens at 9 AM."


def test_chat_passes_model_and_params(mock_openai):
    """chat() forwards model, max_tokens, and temperature to the API."""
    mock_openai.chat.completions.create.return_value = _make_completion("ok")
    client = GroqClient(model="m", max_tokens=100, temperature=0.5)

    client.chat([{"role": "user", "content": "hi"}])

    call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "m"
    assert call_kwargs["max_tokens"] == 100
    assert call_kwargs["temperature"] == 0.5


# --- Error handling ---

def test_api_timeout_error_returns_fallback(mock_openai):
    """APITimeoutError produces the general fallback message."""
    mock_openai.chat.completions.create.side_effect = APITimeoutError(
        request=MagicMock(),
    )
    client = GroqClient()

    result = client.chat([{"role": "user", "content": "hi"}])

    assert result == FALLBACK_GENERAL


def test_api_error_returns_fallback(mock_openai):
    """APIError produces the general fallback message."""
    mock_openai.chat.completions.create.side_effect = APIError(
        message="server error",
        request=MagicMock(),
        body=None,
    )
    client = GroqClient()

    result = client.chat([{"role": "user", "content": "hi"}])

    assert result == FALLBACK_GENERAL


# --- Conversation history preserved ---

def test_conversation_history_forwarded(mock_openai):
    """User and assistant messages are forwarded after the system prompt."""
    mock_openai.chat.completions.create.return_value = _make_completion("reply")
    client = GroqClient()

    history = [
        {"role": "user", "content": "Do you have Dune?"},
        {"role": "assistant", "content": "Yes, we have Dune by Frank Herbert."},
        {"role": "user", "content": "Is it available?"},
    ]
    client.chat(history)

    sent = mock_openai.chat.completions.create.call_args.kwargs["messages"]
    assert len(sent) == 4
    assert sent[1:] == history


# ---------------------------------------------------------------------------
# Property-based tests (hypothesis)
# ---------------------------------------------------------------------------

from hypothesis import given, settings
from hypothesis import strategies as st


def _message_strategy():
    """Strategy that generates a list of user/assistant message dicts."""
    return st.lists(
        st.fixed_dictionaries(
            {
                "role": st.sampled_from(["user", "assistant"]),
                "content": st.text(min_size=1, max_size=200),
            }
        ),
        min_size=0,
        max_size=10,
    )


@given(messages=_message_strategy())
@settings(max_examples=100)
def test_property_system_prompt_always_included(messages):
    """For any conversation history, the system prompt is always the first
    message sent to the API."""
    with patch("app.groq_client.OpenAI") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_instance.chat.completions.create.return_value = _make_completion("ok")

        client = GroqClient()
        client.chat(messages)

        sent_messages = mock_instance.chat.completions.create.call_args.kwargs["messages"]

        assert len(sent_messages) >= 1
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[0]["content"] == SYSTEM_PROMPT
        assert sent_messages[1:] == messages


@given(
    messages=_message_strategy(),
    max_tokens=st.integers(min_value=1, max_value=4096),
)
@settings(max_examples=100)
def test_property_token_limit_always_set(messages, max_tokens):
    """For any call, max_tokens is always a positive integer in the API request."""
    with patch("app.groq_client.OpenAI") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_instance.chat.completions.create.return_value = _make_completion("ok")

        client = GroqClient(max_tokens=max_tokens)
        client.chat(messages)

        call_kwargs = mock_instance.chat.completions.create.call_args.kwargs
        assert "max_tokens" in call_kwargs
        assert isinstance(call_kwargs["max_tokens"], int)
        assert call_kwargs["max_tokens"] > 0
        assert call_kwargs["max_tokens"] == max_tokens
