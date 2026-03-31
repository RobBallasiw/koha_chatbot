"""Query classifier — uses Groq LLM to determine patron intent."""

import json
import logging

from app.groq_client import GroqClient
from app.models import ClassificationResult

logger = logging.getLogger(__name__)

# Confidence threshold below which the intent is forced to "unclear".
CONFIDENCE_THRESHOLD = 0.6

CLASSIFICATION_PROMPT = (
    "You are a query classifier for a library chatbot. "
    "Classify the following patron message into one of these intents:\n"
    '- "catalog_search": the patron wants to find, search for, or look up books or other library materials\n'
    '- "library_info": the patron is asking about library hours, policies, fines, fees, or general information\n'
    '- "unclear": the message does not clearly fit either category\n\n'
    "Respond with ONLY a JSON object in this exact format (no extra text):\n"
    '{{"intent": "<intent>", "confidence": <float between 0 and 1>}}\n\n'
    "Patron message: {message}"
)

VALID_INTENTS = {"catalog_search", "library_info", "unclear"}


def classify_query(
    client: GroqClient,
    message: str,
    conversation_history: list[dict] | None = None,
) -> ClassificationResult:
    """Classify a patron message as a catalog search, library info query, or unclear.

    Parameters
    ----------
    client:
        A configured :class:`GroqClient` instance.
    message:
        The patron's latest message text.
    conversation_history:
        Optional prior conversation turns as ``{"role": ..., "content": ...}`` dicts.

    Returns
    -------
    ClassificationResult
        The classification with *intent* and *confidence*.
    """
    prompt = CLASSIFICATION_PROMPT.format(message=message)

    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": prompt})

    raw_response = client.chat(messages)

    return _parse_classification(raw_response)


def _parse_classification(raw: str) -> ClassificationResult:
    """Parse the LLM's raw text into a :class:`ClassificationResult`.

    Falls back to ``intent="unclear", confidence=0.0`` when parsing fails
    or the response contains invalid values.
    """
    try:
        data = json.loads(raw)
        intent = data.get("intent", "unclear")
        confidence = float(data.get("confidence", 0.0))

        # Validate intent value.
        if intent not in VALID_INTENTS:
            intent = "unclear"
            confidence = 0.0

        # Clamp confidence to [0, 1].
        confidence = max(0.0, min(1.0, confidence))

        # Force "unclear" when confidence is below threshold.
        if confidence < CONFIDENCE_THRESHOLD:
            intent = "unclear"

        return ClassificationResult(intent=intent, confidence=confidence)
    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        logger.warning("Failed to parse classification response: %s", exc)
        return ClassificationResult(intent="unclear", confidence=0.0)
