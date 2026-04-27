"""Library info handler — loads library data and answers patron questions."""

import json
import logging
import sys

from app.groq_client import GroqClient
from app.models import LibraryInfo

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"hours", "fines", "policies"}

CATEGORY_CLASSIFY_SYSTEM = (
    "You are a category classifier for a library information system. "
    "Given a patron's message, determine which category of library information they need. "
    "Respond with ONLY a JSON object, no other text.\n\n"
    "Categories:\n"
    '- "hours": anything about opening hours, schedules, locations, addresses, branches, where the library is, directions, visiting\n'
    '- "policies": anything about borrowing rules, limits, renewals, membership, library cards, loans\n'
    '- "fines": anything about fines, fees, overdue charges, lost items, penalties, costs\n'
    '- "all": the question spans multiple categories or is a general library question\n'
    '- "none": the message has nothing to do with library information\n\n'
    "Respond in this exact format:\n"
    '{"category": "<category>"}'
)

CATEGORY_CLASSIFY_PROMPT = 'Patron message: "{message}"'

CONTACT_STAFF_MESSAGE = (
    "I'm sorry, I don't have that information available. "
    "Please contact library staff for further assistance."
)

INFO_RESPONSE_PROMPT = (
    "A patron asked: \"{message}\"\n\n"
    "Here is the relevant library information:\n"
    "{data}\n\n"
    "Rules:\n"
    "- Answer in a friendly way using ONLY the data above.\n"
    "- Do NOT start with 'I'm Hero' or introduce yourself — just answer the question directly.\n"
    "- For hours questions: include the specific hours for EVERY location listed. Do not skip any location.\n"
    "- Fines and policies apply to ALL locations — do NOT repeat them per location.\n"
    "- Write in natural flowing sentences. Do NOT use bullet points, dashes, or lists.\n"
    "- Use 1 emoji at the end."
)


def _resolve_library_info_path(file_path: str) -> str:
    """Resolve the library info path, trying the project root as a fallback."""
    import os
    if os.path.isfile(file_path):
        return file_path
    # Try relative to this file's directory (works on Vercel)
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(base, file_path)
    if os.path.isfile(candidate):
        return candidate
    return file_path


def load_library_info(file_path: str) -> LibraryInfo:
    """Load and validate library information from a JSON file.

    Supports both multi-location format (with ``locations`` key) and
    legacy single-location format (top-level hours/policies/fines).
    """
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


_HOURS_KEYWORDS = {"hours", "hour", "open", "close", "closing", "opening", "schedule", "time",
                   "address", "location", "locations", "loc", "where", "directions", "branch", "branches", "visit", "map"}
_FINES_KEYWORDS = {"fine", "fines", "fee", "fees", "overdue", "penalty", "charge", "cost", "lost"}
_POLICIES_KEYWORDS = {"policy", "policies", "borrow", "borrowing", "renew", "renewal",
                      "member", "membership", "limit", "rule", "rules", "loan", "card"}


def _keyword_fallback(message: str) -> str | None:
    """Fast keyword-based category matching as fallback when LLM is unavailable."""
    words = set(message.lower().replace("?", " ").replace("!", " ").split())
    if words & _HOURS_KEYWORDS:
        return "hours"
    if words & _FINES_KEYWORDS:
        return "fines"
    if words & _POLICIES_KEYWORDS:
        return "policies"
    return None


def _classify_category(client: GroqClient, message: str) -> str | None:
    """Determine which library info category the patron needs.
    Uses fast keyword matching first, falls back to LLM only when needed."""
    # Try fast keyword match first (avoids slow LLM call)
    keyword_result = _keyword_fallback(message)
    if keyword_result:
        return keyword_result

    # Fall back to LLM for ambiguous messages
    prompt = CATEGORY_CLASSIFY_PROMPT.format(message=message)
    raw = client.chat_with_system(CATEGORY_CLASSIFY_SYSTEM, [{"role": "user", "content": prompt}])
    logger.info("Category classification raw: %s", raw)
    try:
        data = json.loads(raw)
        category = data.get("category", "none")
        if category in VALID_CATEGORIES:
            return category
        if category == "all":
            return "all"
        return None
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Failed to parse category classification: %s", raw)
        return None


def _group_hours(hours: dict[str, str]) -> str:
    """Group days with the same hours into ranges like 'Mon–Fri: 8:00 AM - 5:00 PM'."""
    day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_short = {"monday": "Mon", "tuesday": "Tue", "wednesday": "Wed", "thursday": "Thu",
                 "friday": "Fri", "saturday": "Sat", "sunday": "Sun"}

    # Build ordered list of (day, time) pairs
    ordered = []
    for day in day_order:
        for key, val in hours.items():
            if key.lower() == day:
                ordered.append((day, val.strip()))
                break

    if not ordered:
        # Fallback: just list whatever keys exist
        return "\n".join(f"  📅 {k}: {v}" for k, v in hours.items())

    # Group consecutive days with the same time
    groups: list[tuple[list[str], str]] = []
    for day, time_val in ordered:
        if groups and groups[-1][1].lower() == time_val.lower():
            groups[-1][0].append(day)
        else:
            groups.append(([day], time_val))

    lines = []
    for days, time_val in groups:
        if len(days) == 1:
            label = day_short[days[0]]
        elif len(days) == 2:
            label = f"{day_short[days[0]]} & {day_short[days[-1]]}"
        else:
            label = f"{day_short[days[0]]}–{day_short[days[-1]]}"
        lines.append(f"  📅 {label}: {time_val}")

    return "\n".join(lines)


def _format_category_data(category: str, library_info: LibraryInfo) -> str:
    """Format the data for a matched category across all locations."""
    if category == "hours":
        locations = library_info.get_all_locations()
        if not locations:
            return "(No location data available)"
        parts: list[str] = []
        for loc_name, loc_info in locations.items():
            if loc_info.hours:
                header = f"📍 {loc_name}"
                if loc_info.address:
                    header += f" ({loc_info.address})"
                grouped = _group_hours(loc_info.hours)
                parts.append(f"{header}\n{grouped}")
        return "\n\n".join(parts) if parts else "(No hours data available)"
    else:
        section: dict[str, str] = getattr(library_info, category, {})
        if not section:
            return "(No data available)"
        label = "Fines" if category == "fines" else "Policies"
        lines = "\n".join(f"• {key}: {value}" for key, value in section.items())
        return f"{label} (applies to all locations):\n{lines}"


def _is_llm_available(client: GroqClient) -> bool:
    """Check if the LLM client is configured with a real API (not local Ollama fallback)."""
    import os
    return bool(os.environ.get("OPENROUTER_API_KEY") or
                "openrouter" in os.environ.get("OLLAMA_URL", "").lower() or
                "groq" in os.environ.get("OLLAMA_URL", "").lower())


def handle_library_info_query(
    client: GroqClient,
    message: str,
    library_info: LibraryInfo,
    conversation_history: list[dict],
) -> str:
    """Handle a library information query from a patron."""
    category = _classify_category(client, message)

    if category is None:
        return CONTACT_STAFF_MESSAGE

    # Build data string
    if category == "all":
        parts = []
        for cat in ("hours", "policies", "fines"):
            cat_data = _format_category_data(cat, library_info)
            if cat_data and "No" not in cat_data:
                parts.append(f"[{cat.upper()}]\n{cat_data}")
        data_str = "\n\n".join(parts) if parts else "(No data available)"
    else:
        data_str = _format_category_data(category, library_info)

    # Try LLM for a conversational reply
    if client and _is_llm_available(client):
        try:
            prompt = INFO_RESPONSE_PROMPT.format(message=message, data=data_str)
            messages: list[dict] = []
            if conversation_history:
                messages.extend(conversation_history[-4:])  # Last 2 turns for context
            messages.append({"role": "user", "content": prompt})
            reply = client.chat(messages)
            if isinstance(reply, str) and reply and "trouble" not in reply.lower() and "moment" not in reply.lower():
                return reply
        except Exception:
            logger.info("LLM unavailable for library info, using formatted data")

    # Fallback: return formatted data directly
    return f"Here's what I found 📚:\n\n{data_str}"
