"""LLM client — wraps communication with a local Ollama instance (OpenAI-compatible API)."""

import logging

from openai import OpenAI, APIError, APITimeoutError, RateLimitError

logger = logging.getLogger(__name__)

# System prompt included in every LLM call to constrain responses.
SYSTEM_PROMPT = (
    "You are LLORA, the virtual library assistant of LORMA Colleges Library. "
    "Never reveal that you are an AI or language model. "
    "You speak warmly and concisely, using 1 emoji at the end of your message. "
    "If asked what your name is, say your name is LLORA, the library's virtual assistant. "
    "You help patrons with: finding books, library hours and locations, policies, fines, and library services. "
    "If asked about something outside these topics, politely redirect them. "
    "Never make up book titles or information. "
    "This is an academic library with textbooks and research materials.\n\n"
    "Library services you know about:\n"
    "- LIBVAS (Library Virtual Assistance Service): Provides guidance and support through Facebook (Lorma Colleges Library), "
    "Email (CHS: chslibrary@lorma.edu, CLI: clilibrary@lorma.edu, High School: jhshlibrary@lorma.edu, "
    "Grade School: pgslibrary@lorma.edu), and Telephone (CHS: +63 72 700 250 loc 360, CLI: +63 72 700 1234 loc 361).\n"
    "- LIRAS (Library Information & Research Service): Includes Document Delivery Service (scanned copies of selected pages "
    "sent to official LORMA email) and Online Renewal Request (renew borrowed materials online).\n"
    "- LIBRAS (Library Remote Access Service): Allows off-campus access to subscribed eBooks, eJournals, online databases, "
    "and Open Educational Resources (OERs).\n"
    "- LibPrintS (Library Printing Service): Students purchase a printing card (Php 100) at the business office, "
    "send PDF to the library email, and pick up printouts after notification."
)

# Default model and generation parameters.
DEFAULT_MODEL = "qwen2.5:1.5b"
DEFAULT_MAX_TOKENS = 256
DEFAULT_TEMPERATURE = 0.7
DEFAULT_OLLAMA_URL = "http://localhost:11434/v1"

# Ordered list of fallback models to try when the primary is rate-limited.
# All are free on OpenRouter. First available one wins.
FALLBACK_MODELS = [
    "openai/gpt-oss-20b:free",
    "openai/gpt-oss-120b:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-3n-e2b-it:free",
    "nvidia/nemotron-nano-9b-v2:free",
]

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
    """LLM client that talks to a local Ollama instance via its OpenAI-compatible API."""

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
        resolved_key = os.environ.get("OPENROUTER_API_KEY") or api_key or "ollama"
        self._client = OpenAI(base_url=base_url, api_key=resolved_key)

    def chat(self, messages: list[dict]) -> str:
        """Send *messages* to the LLM and return the assistant reply."""
        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        return self._send(full_messages)

    def chat_with_system(self, system_prompt: str, messages: list[dict]) -> str:
        """Send *messages* with a custom system prompt."""
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        return self._send(full_messages)

    def _send(self, messages: list[dict]) -> str:
        """Send messages, automatically falling back through FALLBACK_MODELS on rate limit."""
        # Build the model chain: primary first, then fallbacks (excluding primary if already listed)
        import os
        primary = self.model
        chain = [primary] + [m for m in FALLBACK_MODELS if m != primary]

        for model in chain:
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                if model != primary:
                    logger.info("Used fallback model: %s", model)
                return response.choices[0].message.content
            except RateLimitError:
                logger.warning("Rate limit hit for model %s, trying next...", model)
                continue
            except APITimeoutError:
                logger.warning("Timeout for model %s, trying next...", model)
                continue
            except APIError as exc:
                # 429 may also surface as APIError
                if "429" in str(exc) or "rate" in str(exc).lower():
                    logger.warning("Rate limit (APIError) for model %s, trying next...", model)
                    continue
                logger.warning("APIError for model %s: %s", model, exc)
                return FALLBACK_GENERAL
            except Exception as exc:
                logger.warning("Unexpected error for model %s: %s", model, exc)
                return FALLBACK_GENERAL

        logger.warning("All models exhausted")
        return FALLBACK_RATE_LIMIT
