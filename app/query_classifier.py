"""Query classifier — uses Groq LLM to determine patron intent."""

import json
import logging

from app.groq_client import GroqClient
from app.models import ClassificationResult

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.4

# Module-level set of FAQ question strings — updated when library info is saved.
# Any message that exactly matches a FAQ question is classified as library_info.
FAQ_QUESTIONS: set[str] = set()

CLASSIFICATION_SYSTEM_PROMPT = (
    "You are a query classifier for a school library chatbot. "
    "Your ONLY job is to classify patron messages into one of these intents. "
    "You must respond with ONLY a JSON object, no other text.\n\n"
    "IMPORTANT: When in doubt, classify as catalog_search.\n\n"
    "Intents:\n"
    '- "catalog_search": the patron wants to find books, authors, topics, or any subject. '
    "This is the DEFAULT for anything that could be a search query.\n"
    '- "library_info": asking about hours, location, address, policies, fines, fees, membership, printing rates, printing procedure, email, contact.\n'
    '- "greeting": ONLY saying hello/hi/hey with no other request.\n'
    '- "unclear": ONLY truly nonsensical or completely unrelated messages.'
)

CLASSIFICATION_PROMPT = (
    "Classify this patron message. Respond with ONLY a JSON object:\n"
    '{{"intent": "<intent>", "confidence": <float between 0 and 1>}}\n\n'
    "Patron message: {message}"
)

VALID_INTENTS = {"catalog_search", "library_info", "greeting", "unclear"}

# Keywords for fast local classification (no LLM call needed)
_INFO_KEYWORDS = {
    "hours", "hour", "open", "close", "closing", "opening", "schedule",
    "address", "location", "locations", "loc", "where", "directions",
    "branch", "branches", "visit", "map",
    "email", "contact", "reach", "mail",
    "fine", "fines", "fee", "fees", "overdue", "penalty", "charge", "lost",
    "policy", "policies", "borrow", "borrowing", "renew", "renewal",
    "member", "membership", "limit", "rule", "rules", "loan", "card",
    "print", "printing", "printer", "photocopy", "scan", "scanning",
    "rate", "rates", "cost", "costs", "price", "prices", "how much",
}

_GREETING_PATTERNS = {
    "hi", "hello", "hey", "yo", "sup", "what up", "whats up", "what's up",
    "good morning", "good afternoon", "good evening", "howdy", "hola",
}

_CATALOG_KEYWORDS = {
    "book", "books", "find", "search", "look", "read", "reading",
    "recommend", "suggest", "title", "author", "isbn", "catalog",
    "subject", "topic", "study", "textbook", "reference", "material",
    "math", "science", "history", "english", "programming", "computer",
    "engineering", "physics", "chemistry", "biology", "literature",
}

_LIBRARIAN_KEYWORDS = {
    "librarian", "staff", "human", "person",
}

_LIBRARIAN_PHRASES = {
    "talk to a librarian", "talk to librarian", "speak to a librarian",
    "speak to librarian", "talk to a human", "talk to a person",
    "i want a librarian", "need a librarian", "live chat",
    "real person please", "connect me to a librarian", "human please",
}


def _quick_classify(message: str) -> str | None:
    """Fast keyword-based classification. Returns intent or None to defer to LLM."""
    lower = message.lower().strip()

    # FAQ exact match — highest priority, before any other check
    if lower in FAQ_QUESTIONS or lower.rstrip("?") in FAQ_QUESTIONS:
        return "library_info"

    # Greetings (exact or near-exact match)
    if lower in _GREETING_PATTERNS or lower.rstrip("!?.") in _GREETING_PATTERNS:
        return "greeting"

    # Talk to a librarian (check phrases first, then keywords)
    if lower.rstrip("!?.") in _LIBRARIAN_PHRASES or lower in _LIBRARIAN_PHRASES:
        return "talk_to_librarian"

    words = set(lower.replace("?", " ").replace("!", " ").replace(".", " ").split())

    if words & _LIBRARIAN_KEYWORDS:
        return "talk_to_librarian"

    # Library info (any keyword present in the message)
    if words & _INFO_KEYWORDS:
        return "library_info"

    # Catalog search (any keyword present)
    if words & _CATALOG_KEYWORDS:
        return "catalog_search"

    return None


def classify_query(
    client: GroqClient,
    message: str,
    conversation_history: list[dict] | None = None,
) -> ClassificationResult:
    """Classify a patron message."""

    # Step 1: Fast keyword pre-check (no LLM needed, works even when rate-limited)
    quick = _quick_classify(message)
    if quick:
        logger.info("Quick-classified as %s: %s", quick, message[:50])
        return ClassificationResult(intent=quick, confidence=0.95)

    # Step 2: Conversation context — if bot just asked "what subject?", it's a search
    if conversation_history:
        for msg in reversed(conversation_history):
            if msg.get("role") == "assistant":
                last_bot = msg.get("content", "").lower()
                cues = ["what subject", "what topic", "looking for", "interested in",
                        "what kind", "narrow down", "give me a hint", "more specific",
                        "can you tell me", "mood for"]
                if any(c in last_bot for c in cues):
                    logger.info("Auto-classifying as catalog_search (follow-up)")
                    return ClassificationResult(intent="catalog_search", confidence=0.95)
                break

    # Step 3: Try LLM classification if available
    import os
    llm_available = bool(os.environ.get("OPENROUTER_API_KEY") or
                         "openrouter" in os.environ.get("OLLAMA_URL", "").lower() or
                         "groq" in os.environ.get("OLLAMA_URL", "").lower())

    if client and llm_available:
        try:
            prompt = CLASSIFICATION_PROMPT.format(message=message)
            messages: list[dict] = []
            if conversation_history:
                messages.extend(conversation_history[-4:])
            messages.append({"role": "user", "content": prompt})
            raw = client.chat_with_system(CLASSIFICATION_SYSTEM_PROMPT, messages)
            result = _parse_classification(raw)
            logger.info("LLM-classified as %s (%.2f): %s", result.intent, result.confidence, message[:50])
            return result
        except Exception:
            logger.info("LLM classification failed, defaulting to catalog_search")

    # Step 4: Default to catalog_search for unmatched messages
    logger.info("Default-classified as catalog_search: %s", message[:50])
    return ClassificationResult(intent="catalog_search", confidence=0.7)


def _parse_classification(raw: str) -> ClassificationResult:
    """Parse the LLM response. Defaults to catalog_search on failure."""
    try:
        data = json.loads(raw)
        intent = data.get("intent", "catalog_search")
        confidence = float(data.get("confidence", 0.0))

        if intent not in VALID_INTENTS:
            intent = "catalog_search"

        confidence = max(0.0, min(1.0, confidence))

        if confidence < CONFIDENCE_THRESHOLD:
            intent = "catalog_search"

        return ClassificationResult(intent=intent, confidence=confidence)
    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        logger.warning("Failed to parse classification: %s", exc)
        return ClassificationResult(intent="catalog_search", confidence=0.0)
