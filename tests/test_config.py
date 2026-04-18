"""Property tests for configuration module.

# Feature: library-ai-chatbot, Property 17: Configuration reads from environment variables
# Feature: library-ai-chatbot, Property 18: Missing required environment variable causes startup failure
"""

import os
import pytest
from hypothesis import given, settings, strategies as st
from app.config import load_settings, REQUIRED_ENV_VARS


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

env_value_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=200,
)


# ---------------------------------------------------------------------------
# Helpers — manually manage env vars so Hypothesis is happy
# ---------------------------------------------------------------------------

def _set_all_env(env_map: dict[str, str]):
    """Set env vars from a dict, saving originals for restore."""
    saved = {}
    for var, val in env_map.items():
        saved[var] = os.environ.get(var)
        os.environ[var] = val
    return saved


def _restore_env(saved: dict[str, str | None]):
    for var, val in saved.items():
        if val is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = val


# ---------------------------------------------------------------------------
# Property 17: Configuration reads from environment variables
# Validates: Requirements 9.1, 9.2, 9.3
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    koha_api_url=env_value_st,
    library_info_path=env_value_st,
)
def test_config_reads_from_environment_variables(
    koha_api_url, library_info_path
):
    """For any set of environment variable values, the Settings object
    should reflect those exact values."""
    env_map = {
        "KOHA_API_URL": koha_api_url,
        "LIBRARY_INFO_PATH": library_info_path,
    }
    saved = _set_all_env(env_map)
    try:
        cfg = load_settings()
        assert cfg.koha_api_url == koha_api_url
        assert cfg.library_info_path == library_info_path
    finally:
        _restore_env(saved)


# ---------------------------------------------------------------------------
# Property 18: Missing required environment variable causes startup failure
# Validates: Requirements 9.5
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    missing_var=st.sampled_from(REQUIRED_ENV_VARS),
    koha_api_url=env_value_st,
    library_info_path=env_value_st,
)
def test_missing_env_var_causes_startup_failure(
    missing_var, koha_api_url, library_info_path
):
    """For any required environment variable that is absent, load_settings
    should raise SystemExit (non-zero)."""
    env_map = {
        "KOHA_API_URL": koha_api_url,
        "LIBRARY_INFO_PATH": library_info_path,
    }

    saved = _set_all_env(env_map)
    # Remove the target variable
    saved_missing = os.environ.pop(missing_var, None)
    try:
        with pytest.raises(SystemExit) as exc_info:
            load_settings()
        assert exc_info.value.code != 0
    finally:
        # Restore the removed var too
        if saved_missing is not None:
            os.environ[missing_var] = saved_missing
        _restore_env(saved)
