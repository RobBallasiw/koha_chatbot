"""Groq LLM client — wraps all communication with the Groq Cloud API."""

from groq import Groq, APIError, RateLimitError, APITimeoutError

# System prompt included in every LLM call to constrain responses.
SYSTEM_PROMPT = (
    "You are a helpful library assistant. You only answer questions related to "
    "the library, its catalog, hours, policies, and fines. If asked about "
    "unrelated topics, politely redirect the conversation to library services."
)

# Default model and generation parameters.
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.7

# Fallback messages returned when the Groq API is unavailable.
FALLBACK_GENERAL = (
    "I'm having trouble processing your request right now. "
    "Please try again in a moment."
)
FALLBACK_RATE_LIMIT = (
    "I'm experiencing high demand. "
    "Your request will be processed shortly."
)


class GroqClient:
    """Thin wrapper around the Groq Python SDK for library chatbot usage.

    Parameters
    ----------
    api_key:
        Groq Cloud API key.
    model:
        Model identifier to use for chat completions.
    max_tokens:
        Maximum number of tokens in the generated response.
    temperature:
        Sampling temperature for response generation.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = Groq(api_key=api_key)

    def chat(self, messages: list[dict]) -> str:
        """Send *messages* to the Groq API and return the assistant reply.

        The library system prompt is always prepended to the messages list
        so the model stays on-topic.

        Parameters
        ----------
        messages:
            Conversation history as a list of ``{"role": ..., "content": ...}``
            dicts (user / assistant turns).

        Returns
        -------
        str
            The assistant's reply text, or a fallback message on failure.
        """
        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            return response.choices[0].message.content
        except RateLimitError:
            return FALLBACK_RATE_LIMIT
        except (APITimeoutError, APIError):
            return FALLBACK_GENERAL
