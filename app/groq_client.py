"""LLM client — wraps communication with a local Ollama instance (OpenAI-compatible API)."""

import logging

from openai import OpenAI, APIError, APITimeoutError

logger = logging.getLogger(__name__)

# System prompt included in every LLM call to constrain responses.
SYSTEM_PROMPT = (
    "Your name is Hero. You are the library assistant chatbot. "
    "When someone asks your name, say 'I'm Hero!' — never say you are an AI or language model. "
    "You speak warmly and concisely, using 1 emoji at the end of your message. "
    "Do NOT start every message with 'I'm Hero' — only say your name if asked. "
    "You help patrons with: finding books, library hours and locations, policies, and fines. "
    "If asked about something outside these topics, politely redirect them. "
    "Never make up book titles or information. "
    "This is an academic library with textbooks and research materials."
)

# Default model and generation parameters.
DEFAULT_MODEL = "qwen2.5:1.5b"
DEFAULT_MAX_TOKENS = 256
DEFAULT_TEMPERATURE = 0.7
DEFAULT_OLLAMA_URL = "http://localhost:11434/v1"

# Fallback messages returned when the LLM is unavailable.
FALLBACK_GENERAL = (
    "Oops, I'm having a little trouble right now 😅 "
    "Give me a moment and try again — I'll be right back!"
)
FALLBACK_RATE_LIMIT = (
    "I'm getting a lot of questions right now! 📚 "
    "Give me about 30 seconds and try again — I promise I'll be ready!"
)


class GroqClient:
    """LLM client that talks to a local Ollama instance via its OpenAI-compatible API.

    The class name is kept as ``GroqClient`` so the rest of the codebase
    doesn't need renaming — it's a drop-in replacement.

    Parameters
    ----------
    api_key:
        Ignored for Ollama (kept for interface compatibility).
    model:
        Ollama model name (e.g. ``llama3.2:3b``).
    max_tokens:
        Maximum number of tokens in the generated response.
    temperature:
        Sampling temperature for response generation.
    base_url:
        Ollama OpenAI-compatible endpoint. Defaults to ``http://localhost:11434/v1``.
    """

    def __init__(
        self,
        api_key: str = "ollama",
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        base_url: str = DEFAULT_OLLAMA_URL,
    ) -> None:
        import os
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Use OpenRouter/Groq API key if set, otherwise fall back to provided key or "ollama"
        resolved_key = os.environ.get("OPENROUTER_API_KEY") or api_key or "ollama"
        self._client = OpenAI(base_url=base_url, api_key=resolved_key)

    def chat(self, messages: list[dict]) -> str:
        """Send *messages* to Ollama and return the assistant reply.

        The library system prompt is always prepended so the model stays on-topic.
        """
        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        return self._send(full_messages)

    def chat_with_system(self, system_prompt: str, messages: list[dict]) -> str:
        """Send *messages* with a custom system prompt.

        Used by the query classifier and other components that need a
        different system-level instruction than the default library prompt.
        """
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        return self._send(full_messages)

    def _send(self, messages: list[dict]) -> str:
        """Send messages to Ollama and return the response text."""
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            return response.choices[0].message.content
        except APITimeoutError:
            logger.warning("Ollama request timed out")
            return FALLBACK_GENERAL
        except (APIError, Exception) as exc:
            logger.warning("Ollama request failed: %s", exc)
            return FALLBACK_GENERAL
