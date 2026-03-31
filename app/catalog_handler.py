"""Catalog search handler — searches Koha catalog and formats results."""

import json
import logging

import httpx

from app.groq_client import GroqClient
from app.models import CatalogRecord, ItemAvailability, SearchParameters

logger = logging.getLogger(__name__)

# Prompt used to extract structured search parameters from a patron message.
EXTRACT_PARAMS_PROMPT = (
    "You are a library catalog search assistant. "
    "Extract search parameters from the patron's message as a JSON object "
    "with these optional fields: title, author, subject, isbn. "
    "Only include fields that are clearly mentioned or implied. "
    "Return ONLY valid JSON, no extra text.\n\n"
    'Patron message: "{message}"'
)

# Prompt used to format catalog results as natural language.
FORMAT_RESULTS_PROMPT = (
    "You are a helpful library assistant. A patron searched the catalog and "
    "the following results were found:\n\n"
    "{results}\n\n"
    "Present these results in a friendly, readable format. "
    "Include the title, author, and call number for each result. "
    "Keep the response concise."
)

NO_RESULTS_MESSAGE = (
    "I wasn't able to find any results matching your search. "
    "You might try:\n"
    "- Using different keywords or a broader search term\n"
    "- Checking the spelling of the title or author name\n"
    "- Searching by subject instead of title"
)

CATALOG_UNAVAILABLE_MESSAGE = (
    "The library catalog is temporarily unavailable. "
    "Please try again later."
)

AVAILABILITY_UNAVAILABLE_MESSAGE = (
    "Availability information is temporarily unavailable."
)


async def extract_search_params(
    client: GroqClient,
    message: str,
    conversation_history: list[dict],
) -> SearchParameters:
    """Use the Groq LLM to extract search parameters from a patron message.

    Parameters
    ----------
    client:
        A configured :class:`GroqClient` instance.
    message:
        The patron's natural language search query.
    conversation_history:
        Prior conversation turns for context.

    Returns
    -------
    SearchParameters
        Extracted parameters. Falls back to ``SearchParameters(title=message)``
        if LLM parsing fails.
    """
    prompt = EXTRACT_PARAMS_PROMPT.format(message=message)

    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": prompt})

    raw = client.chat(messages)

    try:
        data = json.loads(raw)
        return SearchParameters(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Failed to parse search params from LLM response: %s", raw)
        return SearchParameters(title=message)


async def search_catalog(
    koha_api_url: str,
    params: SearchParameters,
) -> list[CatalogRecord]:
    """Query the Koha REST API for catalog records matching *params*.

    Parameters
    ----------
    koha_api_url:
        Base URL of the Koha REST API (e.g. ``http://koha.example.com``).
    params:
        Structured search parameters extracted from the patron query.

    Returns
    -------
    list[CatalogRecord]
        Matching records, or an empty list on error.
    """
    query_parts: list[str] = []
    if params.title:
        query_parts.append(f"ti={params.title}")
    if params.author:
        query_parts.append(f"au={params.author}")
    if params.subject:
        query_parts.append(f"su={params.subject}")
    if params.isbn:
        query_parts.append(f"nb={params.isbn}")

    if not query_parts:
        return []

    q = " AND ".join(query_parts)
    url = f"{koha_api_url.rstrip('/')}/api/v1/biblios"

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.get(url, params={"q": q})
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, Exception) as exc:
        logger.error("Koha catalog search failed: %s", exc)
        return []

    records: list[CatalogRecord] = []
    for item in data:
        records.append(
            CatalogRecord(
                title=item.get("title", "Unknown Title"),
                author=item.get("author", "Unknown Author"),
                call_number=item.get("call_number"),
                isbn=item.get("isbn"),
            )
        )
    return records


async def check_availability(
    koha_api_url: str,
    biblio_id: str,
) -> list[ItemAvailability]:
    """Query the Koha REST API for item-level availability of a biblio.

    Parameters
    ----------
    koha_api_url:
        Base URL of the Koha REST API.
    biblio_id:
        The bibliographic record ID to check.

    Returns
    -------
    list[ItemAvailability]
        Availability info for each copy, or an empty list on error.
    """
    url = f"{koha_api_url.rstrip('/')}/api/v1/biblios/{biblio_id}/items"

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.get(url)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, Exception) as exc:
        logger.error("Koha availability check failed: %s", exc)
        return []

    items: list[ItemAvailability] = []
    for entry in data:
        items.append(
            ItemAvailability(
                branch=entry.get("branch", "Unknown Branch"),
                status=entry.get("status", "unknown"),
                call_number=entry.get("call_number"),
                due_date=entry.get("due_date"),
            )
        )
    return items


def format_catalog_results(records: list[CatalogRecord]) -> str:
    """Format catalog records into a readable string.

    Parameters
    ----------
    records:
        List of catalog records to format.

    Returns
    -------
    str
        A human-readable string listing each record's title, author,
        and call number.
    """
    lines: list[str] = []
    for i, rec in enumerate(records, start=1):
        parts = [f"{i}. {rec.title} by {rec.author}"]
        if rec.call_number:
            parts.append(f"   Call Number: {rec.call_number}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


def format_availability(items: list[ItemAvailability]) -> str:
    """Format item availability grouped by branch.

    Parameters
    ----------
    items:
        List of item availability entries.

    Returns
    -------
    str
        A human-readable string with items grouped by branch, showing
        status, call number, and due date for each copy.
    """
    if not items:
        return AVAILABILITY_UNAVAILABLE_MESSAGE

    # Group items by branch.
    branches: dict[str, list[ItemAvailability]] = {}
    for item in items:
        branches.setdefault(item.branch, []).append(item)

    lines: list[str] = []
    for branch, branch_items in branches.items():
        lines.append(f"{branch}:")
        for item in branch_items:
            parts = [f"  - Status: {item.status}"]
            if item.call_number:
                parts.append(f"    Call Number: {item.call_number}")
            if item.due_date:
                parts.append(f"    Due Date: {item.due_date}")
            lines.append("\n".join(parts))
    return "\n".join(lines)


async def handle_catalog_query(
    client: GroqClient,
    message: str,
    koha_api_url: str,
    conversation_history: list[dict],
) -> str:
    """Main entry point for catalog search queries.

    Extracts search parameters from the patron message, queries the Koha
    catalog, and returns a natural language response.

    Parameters
    ----------
    client:
        A configured :class:`GroqClient` instance.
    message:
        The patron's latest message text.
    koha_api_url:
        Base URL of the Koha REST API.
    conversation_history:
        Prior conversation turns.

    Returns
    -------
    str
        A natural language response with search results, a "no results"
        message, or an error fallback.
    """
    params = await extract_search_params(client, message, conversation_history)

    records = await search_catalog(koha_api_url, params)

    if records is None:
        return CATALOG_UNAVAILABLE_MESSAGE

    if not records:
        return NO_RESULTS_MESSAGE

    results_text = format_catalog_results(records)

    prompt = FORMAT_RESULTS_PROMPT.format(results=results_text)
    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": prompt})

    return client.chat(messages)
