"""Library info handler — loads library data and answers patron questions."""

import json
import logging
import sys

from app.groq_client import GroqClient
from app.models import LibraryInfo

logger = logging.getLogger(__name__)

# Keywords used to match patron queries to info categories.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "hours": ["hours", "open", "close", "closing", "opening", "schedule", "time"],
    "fines": ["fine", "fee", "overdue", "penalty", "charge", "cost", "lost"],
    "policies": [
        "policy",
        "policies",
        "borrow",
        "renew",
        "renewal",
        "member",
        "membership",
        "limit",
        "rule",
        "loan",
    ],
}

CONTACT_STAFF_MESSAGE = (
    "I'm sorry, I don't have that information available. "
    "Please contact library staff for further assistance."
)

INFO_RESPONSE_PROMPT = (
    "You are a helpful library assistant. A patron asked the following question:\n\n"
    '"{message}"\n\n'
    "Here is the relevant library information ({category}):\n"
    "{data}\n\n"
    "Using ONLY the data above, provide a friendly, concise answer to the patron's question. "
    "Do not make up information that is not in the data."
)


def load_library_info(file_path: str) -> LibraryInfo:
    """Load and validate library information from a JSON file.

    Parameters
    ----------
    file_path:
        Path to the JSON file containing library info.

    Returns
    -------
    LibraryInfo
        Parsed and validated library information.

    Raises
    ------
    SystemExit
        If the file is not found or contains malformed data.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(
            f"Error: Library info file not found at '{file_path}'.",
            file=sys.stderr,
        )
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(
            f"Error: Library info file at '{file_path}' is malformed: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        return LibraryInfo(**data)
    except Exception as exc:
        print(
            f"Error: Library info file at '{file_path}' has invalid structure: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


def _match_category(message: str) -> str | None:
    """Match a patron message to a library info category via keyword matching.

    Returns the category name ("hours", "fines", or "policies") or ``None``
    if no keywords match.
    """
    lower = message.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return category
    return None


def _format_category_data(category: str, library_info: LibraryInfo) -> str:
    """Format the data for a matched category as a readable string."""
    section: dict[str, str] = getattr(library_info, category)
    return "\n".join(f"- {key}: {value}" for key, value in section.items())


def handle_library_info_query(
    client: GroqClient,
    message: str,
    library_info: LibraryInfo,
    conversation_history: list[dict],
) -> str:
    """Handle a library information query from a patron.

    Parameters
    ----------
    client:
        A configured :class:`GroqClient` instance.
    message:
        The patron's latest message text.
    library_info:
        The loaded :class:`LibraryInfo` data.
    conversation_history:
        Prior conversation turns as ``{"role": ..., "content": ...}`` dicts.

    Returns
    -------
    str
        A natural language response, or a "contact staff" message when
        no relevant info category is found.
    """
    category = _match_category(message)

    if category is None:
        return CONTACT_STAFF_MESSAGE

    data_str = _format_category_data(category, library_info)
    prompt = INFO_RESPONSE_PROMPT.format(
        message=message,
        category=category,
        data=data_str,
    )

    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": prompt})

    return client.chat(messages)
