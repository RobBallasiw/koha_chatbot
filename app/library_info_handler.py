"""Library info handler — loads library data and answers patron questions."""

import json
import logging

from app.groq_client import GroqClient
from app.models import LibraryInfo

logger = logging.getLogger(__name__)

CONTACT_STAFF_MESSAGE = (
    "I'm sorry, I don't have that information available. "
    "Please contact library staff for further assistance."
)

FAQ_RESPONSE_PROMPT = (
    "A patron asked: \"{message}\"\n\n"
    "Here is the relevant library information:\n"
    "{data}\n\n"
    "Rules:\n"
    "- Answer in a friendly, conversational way using ONLY the data above.\n"
    "- Do NOT introduce yourself — just answer the question directly.\n"
    "- Write in natural flowing sentences. Do NOT use bullet points, dashes, or lists.\n"
    "- Use 1 emoji at the end."
)


def _resolve_library_info_path(file_path: str) -> str:
    """Resolve the library info path, trying the project root as a fallback."""
    import os
    if os.path.isfile(file_path):
        return file_path
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(base, file_path)
    if os.path.isfile(candidate):
        return candidate
    return file_path


def load_library_info(file_path: str) -> LibraryInfo:
    """Load and validate library information from a JSON file."""
    resolved = _resolve_library_info_path(file_path)
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error("Library info file not found at '%s' (resolved: '%s')", file_path, resolved)
        return LibraryInfo()
    except json.JSONDecodeError as exc:
        logger.error("Library info file at '%s' is malformed: %s", resolved, exc)
        return LibraryInfo()

    try:
        return LibraryInfo(**data)
    except Exception as exc:
        logger.error("Library info file at '%s' has invalid structure: %s", resolved, exc)
        return LibraryInfo()


def _is_llm_available(client: GroqClient) -> bool:
    """Check if the LLM client is configured with a real API."""
    import os
    return bool(os.environ.get("OPENROUTER_API_KEY") or
                "openrouter" in os.environ.get("OLLAMA_URL", "").lower() or
                "groq" in os.environ.get("OLLAMA_URL", "").lower())


def _find_matching_faqs(message: str, library_info: LibraryInfo) -> list:
    """Return FAQ items whose question or label is relevant to the message."""
    if not library_info.faqs:
        return []
    msg_lower = message.strip().lower()
    words = set(msg_lower.replace("?", " ").replace("!", " ").split())

    # 1. Exact question match — highest priority
    for faq in library_info.faqs:
        if faq.question.strip().lower() == msg_lower:
            return [faq]

    # 2. Keyword match against question and label
    scored = []
    for faq in library_info.faqs:
        faq_words = set((faq.question + " " + faq.label).lower().replace("?", " ").split())
        overlap = len(words & faq_words)
        if overlap > 0:
            scored.append((overlap, faq))
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return [faq for score, faq in scored[:3] if score >= 1]

    return []


def handle_library_info_query(
    client: GroqClient,
    message: str,
    library_info: LibraryInfo,
    conversation_history: list[dict],
) -> str:
    """Handle a library information query from a patron."""
    if not library_info or not library_info.faqs:
        return CONTACT_STAFF_MESSAGE

    matches = _find_matching_faqs(message, library_info)

    if not matches:
        return CONTACT_STAFF_MESSAGE

    # Exact match with content — return directly
    msg_lower = message.strip().lower()
    if len(matches) == 1 and matches[0].question.strip().lower() == msg_lower:
        if matches[0].content.strip():
            return matches[0].content.strip()

    # Build data string from matched FAQ content
    data_parts = []
    for faq in matches:
        if faq.content.strip():
            data_parts.append(f"[{faq.question}]\n{faq.content.strip()}")

    if not data_parts:
        return CONTACT_STAFF_MESSAGE

    data_str = "\n\n".join(data_parts)

    # Try LLM for a conversational reply
    if client and _is_llm_available(client):
        try:
            prompt = FAQ_RESPONSE_PROMPT.format(message=message, data=data_str)
            messages: list[dict] = []
            if conversation_history:
                messages.extend(conversation_history[-4:])
            messages.append({"role": "user", "content": prompt})
            reply = client.chat(messages)
            if isinstance(reply, str) and reply and "trouble" not in reply.lower() and "moment" not in reply.lower():
                return reply
        except Exception:
            logger.info("LLM unavailable for library info, using raw FAQ content")

    return f"{data_str} 📚"
