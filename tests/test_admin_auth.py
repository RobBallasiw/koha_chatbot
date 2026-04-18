"""Property-based tests for admin authentication.

Tests Property 10 from the admin-chat-monitoring design.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

from app.admin_auth import verify_admin_key


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty API keys (printable strings, reasonable length)
api_keys = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
)


# ---------------------------------------------------------------------------
# Property 10: Authentication gate
# Feature: admin-chat-monitoring, Property 10: Authentication gate
# ---------------------------------------------------------------------------
# **Validates: Requirements 5.1, 5.2, 5.4, 5.5**


@given(expected_key=api_keys)
@settings(max_examples=100)
def test_missing_key_returns_401(expected_key):
    """A request with a missing API key (None) should raise 401."""
    with patch("app.admin_auth.get_admin_api_key", return_value=expected_key):
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key=None)
        assert exc_info.value.status_code == 401


@given(expected_key=api_keys, provided_key=api_keys)
@settings(max_examples=100)
def test_wrong_key_returns_401(expected_key, provided_key):
    """A request with an incorrect API key should raise 401."""
    # Only test when the keys actually differ
    if provided_key == expected_key:
        return

    with patch("app.admin_auth.get_admin_api_key", return_value=expected_key):
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key=provided_key)
        assert exc_info.value.status_code == 401


@given(expected_key=api_keys)
@settings(max_examples=100)
def test_correct_key_does_not_return_401(expected_key):
    """A request with the correct API key should NOT raise 401."""
    with patch("app.admin_auth.get_admin_api_key", return_value=expected_key):
        # Should not raise any exception
        result = verify_admin_key(x_admin_key=expected_key)
        assert result is None


@given(provided_key=api_keys)
@settings(max_examples=100)
def test_unconfigured_key_returns_401(provided_key):
    """When ADMIN_API_KEY is not configured (None), all requests should get 401."""
    with patch("app.admin_auth.get_admin_api_key", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key=provided_key)
        assert exc_info.value.status_code == 401
