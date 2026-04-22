"""Catalog search handler — searches Koha catalog and formats results."""

import json
import logging
import xml.etree.ElementTree as ET

import httpx

from app.groq_client import GroqClient
from app.models import CatalogRecord, ItemAvailability, SearchParameters

logger = logging.getLogger(__name__)

# Prompt used to extract structured search parameters from a patron message.
EXTRACT_SYSTEM_PROMPT = (
    "Extract search keywords from the message. Return ONLY a JSON object with optional fields: "
    "title, author, subject, isbn. No extra text."
)

EXTRACT_PARAMS_PROMPT = (
    'Patron message: "{message}"'
)

# Prompt used to format catalog results as natural language.
FORMAT_RESULTS_PROMPT = (
    "You are a helpful library assistant. A patron searched the catalog and "
    "the following results were found:\n\n"
    "{results}\n\n"
    "Present these results in a friendly, readable format. "
    "Include the title, author, and call number for each result. "
    "IMPORTANT: For each result that has a 'View in catalog' URL, you MUST include "
    "the full URL as a clickable link so the patron can view the book details. "
    "Format links as: [View in catalog](URL) "
    "Keep the response concise."
)

NO_RESULTS_MESSAGE = (
    "Hmm, I couldn't find that one in our catalog 🔍 "
    "A few things that might help:\n"
    "• Try different keywords or a broader topic\n"
    "• Double-check the spelling\n"
    "• Search by subject instead of a specific title\n\n"
    "Or just tell me what you're in the mood for and I'll dig around! 📚"
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

    raw = client.chat_with_system(EXTRACT_SYSTEM_PROMPT, messages)

    try:
        # Strip markdown code blocks if the LLM wraps JSON in them
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]  # remove ```json line
            cleaned = cleaned.rsplit("```", 1)[0]  # remove closing ```
            cleaned = cleaned.strip()
        data = json.loads(cleaned)
        logger.info("LLM extracted search params: %s", data)
        return SearchParameters(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Failed to parse search params from LLM response: %s", raw)
        return SearchParameters(title=message)


async def search_catalog_raw(
    koha_api_url: str,
    query: str,
) -> list[CatalogRecord]:
    """Search the Koha OPAC with a raw keyword string, like the search bar.

    This mirrors what happens when a patron types into the Koha OPAC
    search box — no field-specific filtering, just plain keyword search.
    """
    if not query or not query.strip():
        return []

    url = f"{koha_api_url.rstrip('/')}/cgi-bin/koha/opac-search.pl"

    # Restrict search to title and author fields only
    scoped_query = f"ti:{query.strip()} OR au:{query.strip()}"

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
            logger.info("Searching Koha at: %s with q=%s", url, scoped_query)
            response = await http.get(
                url,
                params={"q": scoped_query, "format": "rss"},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            )
            logger.info("Koha response status: %s, length: %s", response.status_code, len(response.text))
            response.raise_for_status()
    except (httpx.HTTPError, Exception) as exc:
        logger.error("Koha catalog raw search failed: %s (type: %s)", exc, type(exc).__name__)
        return []

    return _parse_rss_results(response.text, koha_api_url)


async def search_catalog(
    koha_api_url: str,
    params: SearchParameters,
) -> list[CatalogRecord]:
    """Query the Koha OPAC RSS search for catalog records matching *params*.

    Uses the public OPAC search endpoint (no authentication required)
    and parses the RSS/XML response.

    Parameters
    ----------
    koha_api_url:
        Base URL of the Koha OPAC (e.g. ``http://localhost``).
    params:
        Structured search parameters extracted from the patron query.

    Returns
    -------
    list[CatalogRecord]
        Matching records, or an empty list on error.
    """
    # Build a keyword query from the extracted parameters.
    query_parts: list[str] = []
    if params.title:
        query_parts.append(params.title)
    if params.author:
        query_parts.append(params.author)
    if params.subject:
        query_parts.append(params.subject)
    if params.isbn:
        query_parts.append(params.isbn)

    if not query_parts:
        return []

    q = " ".join(query_parts)
    url = f"{koha_api_url.rstrip('/')}/cgi-bin/koha/opac-search.pl"

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
            response = await http.get(
                url,
                params={"q": q, "format": "rss"},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            )
            response.raise_for_status()
    except (httpx.HTTPError, Exception) as exc:
        logger.error("Koha catalog search failed: %s (type: %s)", exc, type(exc).__name__)
        return []

    return _parse_rss_results(response.text, koha_api_url)


def _parse_rss_results(xml_text: str, koha_api_url: str) -> list[CatalogRecord]:
    """Parse Koha OPAC RSS/XML response into CatalogRecord list."""
    import re

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.error("Failed to parse Koha RSS response: %s", exc)
        return []

    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    }

    records: list[CatalogRecord] = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        title = title_el.text.strip() if title_el is not None and title_el.text else "Unknown Title"

        # Extract author: try dc:creator first, then parse from description "By Author.<br />"
        creator_el = item.find("dc:creator", ns)
        author = None
        if creator_el is not None and creator_el.text and creator_el.text.strip():
            author = creator_el.text.strip()

        if not author:
            desc_el = item.find("description")
            if desc_el is not None and desc_el.text:
                by_match = re.search(r"By\s+(.+?)\.\s*<br", desc_el.text)
                if by_match:
                    author = by_match.group(1).strip()

        if not author:
            author = "Unknown Author"

        # Extract ISBN from dc:identifier if it contains one.
        isbn = None
        ident_el = item.find("dc:identifier", ns)
        if ident_el is not None and ident_el.text:
            ident_text = ident_el.text.strip()
            if ident_text.startswith("ISBN:"):
                isbn_val = ident_text[5:].strip()
                if isbn_val:
                    isbn = isbn_val

        # Extract biblionumber from the link for potential availability lookups.
        link_el = item.find("link")
        biblio_id = None
        opac_url = None
        if link_el is not None and link_el.text:
            link_text = link_el.text.strip()
            # Build full OPAC URL from the relative link.
            opac_url = f"{koha_api_url.rstrip('/')}{link_text}"
            parts = link_text.split("biblionumber=")
            if len(parts) > 1:
                biblio_id = parts[1].strip()

        records.append(
            CatalogRecord(
                title=title,
                author=author,
                call_number=None,
                isbn=isbn,
                opac_url=opac_url,
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
        if rec.opac_url:
            parts.append(f"   View in catalog: {rec.opac_url}")
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


# Prompt used to broaden search terms when the first search returns nothing.
BROADEN_SEARCH_PROMPT = (
    "The library catalog search returned no results for these parameters:\n"
    "{params}\n\n"
    "The patron's original message was: \"{message}\"\n\n"
    "Generate alternative, broader search parameters as a JSON object with "
    "fields: title, author, subject, isbn. Try:\n"
    "- Expanding any acronyms or abbreviations fully\n"
    "- Using broader subject terms\n"
    "- Removing overly specific words\n"
    "- Using the subject field instead of title for topic searches\n"
    "Return ONLY valid JSON, no extra text."
)


async def _broaden_search(
    client: GroqClient,
    message: str,
    original_params: SearchParameters,
    conversation_history: list[dict],
) -> SearchParameters | None:
    """Ask the LLM to generate broader search terms after a failed search."""
    params_str = json.dumps(original_params.model_dump(exclude_none=True))
    prompt = BROADEN_SEARCH_PROMPT.format(params=params_str, message=message)

    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": prompt})

    raw = client.chat(messages)
    try:
        data = json.loads(raw)
        broader = SearchParameters(**data)
        logger.info("Broadened search: %s -> %s", params_str, data)
        return broader
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Failed to parse broadened search params: %s", raw)
        return None


def _params_to_query(params: SearchParameters) -> str:
    """Convert search parameters to a normalized query string for comparison."""
    parts = []
    if params.title:
        parts.append(params.title.lower().strip())
    if params.author:
        parts.append(params.author.lower().strip())
    if params.subject:
        parts.append(params.subject.lower().strip())
    if params.isbn:
        parts.append(params.isbn.strip())
    return " ".join(sorted(parts))


def _extract_keywords(message: str) -> str:
    """Extract search keywords from a patron message by stripping common filler.

    This mimics what a patron would type into the Koha search bar —
    just the meaningful keywords.
    """
    import re
    # Strip backslashes and whitespace
    lower = message.lower().strip().replace("\\", "")
    # Remove common conversational prefixes
    prefixes = [
        r"^(can you |could you |please |i want to |i'd like to |i would like to )",
        r"^(i need to |i gotta |i wanna |i have to )",
        r"^(search for |find me |find |look up |look for |show me |get me |recommend |suggest )",
        r"^(books? about |books? on |books? related to |books? for |books? by )",
        r"^(any |some |a few )",
        r"^(do you have |are there |is there )",
        r"^(fetch |give |bring )",
    ]
    cleaned = lower
    for pattern in prefixes:
        cleaned = re.sub(pattern, "", cleaned)
    # Second pass to catch chained prefixes like "can you find me"
    for pattern in prefixes:
        cleaned = re.sub(pattern, "", cleaned)
    # Strip "by" prefix only if it's a standalone word (author search like "books by lee rv" → "lee rv")
    cleaned = re.sub(r"^by\s+", "", cleaned)
    # Remove trailing filler
    cleaned = re.sub(r"(please|thanks|thank you|pls|\?|!|\.)+$", "", cleaned)
    cleaned = cleaned.strip()
    return cleaned if cleaned else message.strip()


VAGUE_FOLLOWUP_MESSAGE = (
    "I'd love to help you find something! 📚 Could you tell me what subject you're interested in? "
    "For example: Science, Math, History, English, Computer Science, or Engineering?"
)

# Words that indicate the patron wants something but hasn't said what
_VAGUE_PATTERNS = {
    "something", "anything", "book", "books", "read", "reading",
    "stuff", "thing", "things", "whatever", "idk", "dunno",
    "nothing specific", "no idea", "surprise me", "me",
    "some", "need", "want", "get", "man", "dude", "bro",
    "lame", "lamee", "lameee", "boring", "help",
    "this", "so", "just", "like", "really", "please", "pls",
}


def _is_vague_query(keywords: str) -> bool:
    """Check if extracted keywords are too vague to search."""
    import re
    cleaned = re.sub(r"[.!?,;:]+", " ", keywords.lower().strip()).strip()
    if len(cleaned) < 3:
        return True
    words = set(cleaned.split())
    if words and words.issubset(_VAGUE_PATTERNS):
        return True
    return False


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
    # Step 0: Check if the query is too vague to search
    raw_keywords = _extract_keywords(message)
    if _is_vague_query(raw_keywords):
        return VAGUE_FOLLOWUP_MESSAGE

    # Step 1: Use LLM to extract the real search term from conversational input
    params = await extract_search_params(client, message, conversation_history)

    # Step 2: Search Koha — try raw keywords first (most reliable), then LLM-extracted terms
    records = []

    # Try raw keywords first — this is what the patron actually meant
    records = await search_catalog_raw(koha_api_url, raw_keywords)

    # If no results, try each LLM-extracted field individually
    if not records:
        for term in [params.author, params.title, params.subject, params.isbn]:
            if term and term.strip():
                records = await search_catalog_raw(koha_api_url, term.strip())
                if records:
                    break

    if records is None:
        return CATALOG_UNAVAILABLE_MESSAGE

    if not records:
        return NO_RESULTS_MESSAGE

    results_text = format_catalog_results(records)
    return f"Here's what I found in the catalog 📚:\n\n{results_text}"
