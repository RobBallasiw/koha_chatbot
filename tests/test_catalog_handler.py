"""Unit tests for the catalog search handler."""

import json
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.catalog_handler import (
    extract_search_params,
    search_catalog,
    check_availability,
    format_catalog_results,
    format_availability,
    handle_catalog_query,
    NO_RESULTS_MESSAGE,
    CATALOG_UNAVAILABLE_MESSAGE,
    AVAILABILITY_UNAVAILABLE_MESSAGE,
)
from app.models import CatalogRecord, ItemAvailability, SearchParameters


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_groq_client(response_text: str) -> MagicMock:
    """Create a mock GroqClient that returns *response_text* from chat() and chat_with_system()."""
    client = MagicMock()
    client.chat.return_value = response_text
    client.chat_with_system.return_value = response_text
    return client


# ---------------------------------------------------------------------------
# extract_search_params
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_search_params_valid_json():
    """LLM returns valid JSON → parsed into SearchParameters."""
    payload = {"title": "The Great Gatsby", "author": "Fitzgerald"}
    client = _make_groq_client(json.dumps(payload))

    result = await extract_search_params(client, "Gatsby by Fitzgerald", [])

    assert isinstance(result, SearchParameters)
    assert result.title == "The Great Gatsby"
    assert result.author == "Fitzgerald"


@pytest.mark.asyncio
async def test_extract_search_params_invalid_json_fallback():
    """LLM returns garbage → falls back to title=message."""
    client = _make_groq_client("not valid json at all")

    result = await extract_search_params(client, "some query", [])

    assert result == SearchParameters(title="some query")


@pytest.mark.asyncio
async def test_extract_search_params_includes_history():
    """Conversation history is forwarded to the LLM."""
    client = _make_groq_client('{"title": "Dune"}')
    history = [{"role": "user", "content": "hi"}]

    await extract_search_params(client, "Dune", history)

    # extract_search_params uses chat_with_system(system_prompt, messages)
    call_messages = client.chat_with_system.call_args[0][1]
    assert call_messages[0] == history[0]


# ---------------------------------------------------------------------------
# search_catalog
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_catalog_empty_params():
    """No search params → empty list without calling API."""
    params = SearchParameters()
    result = await search_catalog("http://koha.test", params)
    assert result == []


@pytest.mark.asyncio
async def test_search_catalog_api_error():
    """Koha API error → empty list returned."""
    params = SearchParameters(title="Test")

    with patch("app.catalog_handler.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.get = AsyncMock(side_effect=Exception("connection refused"))
        MockClient.return_value = mock_instance

        result = await search_catalog("http://koha.test", params)
        assert result == []


@pytest.mark.asyncio
async def test_search_catalog_parses_response():
    """Koha API returns RSS records → parsed into CatalogRecord list."""
    params = SearchParameters(author="Morrison")
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
      <channel>
        <item>
          <title>Beloved</title>
          <dc:creator>Toni Morrison</dc:creator>
          <dc:identifier>ISBN:123</dc:identifier>
          <link>/cgi-bin/koha/opac-detail.pl?biblionumber=1</link>
        </item>
        <item>
          <title>Song of Solomon</title>
          <dc:creator>Toni Morrison</dc:creator>
          <link>/cgi-bin/koha/opac-detail.pl?biblionumber=2</link>
        </item>
      </channel>
    </rss>"""

    mock_response = MagicMock()
    mock_response.text = rss_xml
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("app.catalog_handler.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.get = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_instance

        result = await search_catalog("http://koha.test", params)

    assert len(result) == 2
    assert result[0].title == "Beloved"
    assert result[0].isbn == "123"
    assert result[1].title == "Song of Solomon"


# ---------------------------------------------------------------------------
# check_availability
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_availability_parses_response():
    """Koha items endpoint → parsed into ItemAvailability list."""
    api_data = [
        {"branch": "Main", "status": "available", "call_number": "813.54 MOR"},
        {"branch": "West", "status": "checked_out", "due_date": "2025-02-01"},
    ]

    mock_response = MagicMock()
    mock_response.json.return_value = api_data
    mock_response.raise_for_status = MagicMock()

    with patch("app.catalog_handler.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.get = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_instance

        result = await check_availability("http://koha.test", "42")

    assert len(result) == 2
    assert result[0].branch == "Main"
    assert result[0].status == "available"
    assert result[1].due_date == "2025-02-01"


@pytest.mark.asyncio
async def test_check_availability_api_error():
    """Koha items endpoint error → empty list."""
    with patch("app.catalog_handler.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.get = AsyncMock(side_effect=Exception("timeout"))
        MockClient.return_value = mock_instance

        result = await check_availability("http://koha.test", "42")
        assert result == []


# ---------------------------------------------------------------------------
# format_catalog_results
# ---------------------------------------------------------------------------

def test_format_catalog_results_includes_all_fields():
    """Formatted output contains title, author, and call number."""
    records = [
        CatalogRecord(title="Beloved", author="Toni Morrison", call_number="813.54 MOR"),
        CatalogRecord(title="Dune", author="Frank Herbert"),
    ]
    result = format_catalog_results(records)

    assert "Beloved" in result
    assert "Toni Morrison" in result
    assert "813.54 MOR" in result
    assert "Dune" in result
    assert "Frank Herbert" in result


def test_format_catalog_results_empty():
    """Empty list → empty string."""
    assert format_catalog_results([]) == ""


# ---------------------------------------------------------------------------
# format_availability
# ---------------------------------------------------------------------------

def test_format_availability_groups_by_branch():
    """Items from the same branch appear together."""
    items = [
        ItemAvailability(branch="Main", status="available", call_number="813.54"),
        ItemAvailability(branch="West", status="checked_out", due_date="2025-03-01"),
        ItemAvailability(branch="Main", status="checked_out", due_date="2025-04-01"),
    ]
    result = format_availability(items)

    # Both Main items should appear under the "Main:" header
    main_idx = result.index("Main:")
    west_idx = result.index("West:")
    # Find all occurrences of "Main" status lines
    assert result.count("Main:") == 1
    assert result.count("West:") == 1
    assert "available" in result
    assert "2025-03-01" in result
    assert "2025-04-01" in result


def test_format_availability_empty():
    """Empty items → unavailable message."""
    assert format_availability([]) == AVAILABILITY_UNAVAILABLE_MESSAGE


def test_format_availability_shows_due_date():
    """Checked-out items show due date."""
    items = [
        ItemAvailability(branch="Main", status="checked_out", due_date="2025-06-15"),
    ]
    result = format_availability(items)
    assert "2025-06-15" in result


def test_format_availability_shows_call_number():
    """Available items show call number."""
    items = [
        ItemAvailability(branch="Main", status="available", call_number="F HER"),
    ]
    result = format_availability(items)
    assert "F HER" in result


# ---------------------------------------------------------------------------
# handle_catalog_query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_catalog_query_no_results():
    """No catalog results → NO_RESULTS_MESSAGE."""
    client = _make_groq_client('{"title": "nonexistent"}')

    with patch("app.catalog_handler.search_catalog", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = []

        result = await handle_catalog_query(client, "nonexistent book", "http://koha.test", [])

    assert result == NO_RESULTS_MESSAGE


@pytest.mark.asyncio
async def test_handle_catalog_query_with_results():
    """Catalog results found → formatted response returned."""
    records = [CatalogRecord(title="Beloved", author="Toni Morrison", call_number="813.54 MOR")]

    client = _make_groq_client('{"title": "Beloved"}')

    with patch("app.catalog_handler.search_catalog_raw", new_callable=AsyncMock) as mock_raw:
        mock_raw.return_value = records

        result = await handle_catalog_query(client, "Beloved", "http://koha.test", [])

    assert "Beloved" in result


# ---------------------------------------------------------------------------
# Property-based tests (hypothesis)
# ---------------------------------------------------------------------------

import asyncio
import re
from hypothesis import given, settings
from hypothesis import strategies as st


def _non_empty_text():
    """Strategy for non-empty printable text strings (no leading/trailing whitespace)."""
    return st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P")),
        min_size=1,
        max_size=200,
    )


def _catalog_record_strategy():
    """Strategy that generates CatalogRecord objects."""
    return st.builds(
        CatalogRecord,
        title=_non_empty_text(),
        author=_non_empty_text(),
        call_number=st.one_of(st.none(), _non_empty_text()),
        isbn=st.one_of(st.none(), _non_empty_text()),
    )


def _item_availability_strategy(
    status_values=("available", "checked_out", "on_hold"),
    force_due_date=False,
):
    """Strategy that generates ItemAvailability objects."""
    due_date_st = (
        _non_empty_text() if force_due_date
        else st.one_of(st.none(), _non_empty_text())
    )
    return st.builds(
        ItemAvailability,
        branch=_non_empty_text(),
        status=st.sampled_from(status_values),
        call_number=st.one_of(st.none(), _non_empty_text()),
        due_date=due_date_st,
    )


# Feature: library-ai-chatbot, Property 1: Search parameter extraction produces valid structure
@given(message=_non_empty_text())
@settings(max_examples=100)
def test_property_search_param_extraction_valid_structure(message):
    """**Validates: Requirements 1.1**

    For any non-empty patron message string, the search parameter extraction
    function should return a valid SearchParameters object where each field is
    either None or a non-empty string.
    """
    # Mock the GroqClient to return a JSON with title = message
    mock_client = MagicMock()
    mock_client.chat.return_value = json.dumps({"title": message})
    mock_client.chat_with_system.return_value = json.dumps({"title": message})

    result = asyncio.run(extract_search_params(mock_client, message, []))

    # Result must be a SearchParameters instance
    assert isinstance(result, SearchParameters)

    # Each field must be None or a non-empty string
    for field_name in ("title", "author", "subject", "isbn"):
        value = getattr(result, field_name)
        assert value is None or (isinstance(value, str) and len(value) > 0), (
            f"Field {field_name} must be None or non-empty string, got {value!r}"
        )

    # At least one field should be non-None (message is non-empty)
    all_values = [result.title, result.author, result.subject, result.isbn]
    assert any(v is not None for v in all_values), (
        "At least one search parameter should be non-None for a non-empty message"
    )


# Feature: library-ai-chatbot, Property 2: Catalog result formatting includes required fields
@given(records=st.lists(_catalog_record_strategy(), min_size=1, max_size=10))
@settings(max_examples=100)
def test_property_catalog_result_formatting_includes_required_fields(records):
    """**Validates: Requirements 1.3**

    For any non-empty list of CatalogRecord objects, the formatted response
    string should contain the title, author, and call number of every record.
    """
    result = format_catalog_results(records)

    for rec in records:
        assert rec.title in result, f"Title {rec.title!r} not found in output"
        assert rec.author in result, f"Author {rec.author!r} not found in output"
        if rec.call_number is not None:
            assert rec.call_number in result, (
                f"Call number {rec.call_number!r} not found in output"
            )


# Feature: library-ai-chatbot, Property 3: Available item response includes location details
@given(
    item=_item_availability_strategy(
        status_values=("available",),
    ).filter(lambda i: i.call_number is not None),
)
@settings(max_examples=100)
def test_property_available_item_includes_location_details(item):
    """**Validates: Requirements 2.2**

    For any ItemAvailability object with status "available" and a non-null
    call_number, the formatted response should contain the branch name and
    call number.
    """
    result = format_availability([item])

    assert item.branch in result, f"Branch {item.branch!r} not found in output"
    assert item.call_number in result, (
        f"Call number {item.call_number!r} not found in output"
    )


# Feature: library-ai-chatbot, Property 4: Checked-out item response includes due date
@given(
    item=_item_availability_strategy(
        status_values=("checked_out",),
        force_due_date=True,
    ),
)
@settings(max_examples=100)
def test_property_checked_out_item_includes_due_date(item):
    """**Validates: Requirements 2.3**

    For any ItemAvailability object with status "checked_out" and a non-null
    due_date, the formatted response should contain the due date value.
    """
    result = format_availability([item])

    assert item.due_date in result, (
        f"Due date {item.due_date!r} not found in output"
    )


# Feature: library-ai-chatbot, Property 5: Multi-copy availability grouped by branch
@given(
    items=st.lists(
        _item_availability_strategy(),
        min_size=2,
        max_size=15,
    ).filter(lambda lst: len({i.branch for i in lst}) >= 2),
)
@settings(max_examples=100)
def test_property_multi_copy_availability_grouped_by_branch(items):
    """**Validates: Requirements 2.4**

    For any list of ItemAvailability objects spanning multiple branches, the
    formatted response should group items by branch such that all items for a
    given branch appear together contiguously (no interleaving of branches).
    """
    result = format_availability(items)

    # Collect the branch names in the order they appear as headers
    branch_header_order = []
    for line in result.splitlines():
        # Branch headers are lines like "BranchName:"
        if line.endswith(":") and not line.startswith(" "):
            branch_name = line[:-1]
            branch_header_order.append(branch_name)

    # Every branch that has items should appear exactly once as a header
    expected_branches = {item.branch for item in items}
    assert set(branch_header_order) == expected_branches, (
        f"Expected branches {expected_branches}, got headers {branch_header_order}"
    )
    # No duplicate headers means items are grouped contiguously
    assert len(branch_header_order) == len(set(branch_header_order)), (
        "Branch headers should appear exactly once (items grouped contiguously)"
    )
