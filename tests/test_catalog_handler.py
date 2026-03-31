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
    """Create a mock GroqClient that returns *response_text* from chat()."""
    client = MagicMock()
    client.chat.return_value = response_text
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

    call_messages = client.chat.call_args[0][0]
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
    """Koha API returns records → parsed into CatalogRecord list."""
    params = SearchParameters(author="Morrison")
    api_data = [
        {"title": "Beloved", "author": "Toni Morrison", "call_number": "813.54 MOR", "isbn": "123"},
        {"title": "Song of Solomon", "author": "Toni Morrison"},
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

        result = await search_catalog("http://koha.test", params)

    assert len(result) == 2
    assert result[0].title == "Beloved"
    assert result[0].call_number == "813.54 MOR"
    assert result[1].call_number is None


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
    """Catalog results found → LLM formats them."""
    records = [CatalogRecord(title="Beloved", author="Toni Morrison", call_number="813.54 MOR")]

    # First call: extract params, second call: format results
    client = MagicMock()
    client.chat.side_effect = [
        '{"title": "Beloved"}',
        "I found Beloved by Toni Morrison (813.54 MOR).",
    ]

    with patch("app.catalog_handler.search_catalog", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = records

        result = await handle_catalog_query(client, "Beloved", "http://koha.test", [])

    assert "Beloved" in result
