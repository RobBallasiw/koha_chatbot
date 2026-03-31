"""Tests for the startup lifecycle wiring in app/main.py."""

import asyncio
from unittest.mock import patch, MagicMock

import pytest

from app.config import Settings
from app.models import LibraryInfo


@pytest.fixture
def _mock_settings():
    return Settings(
        koha_api_url="http://koha.example.com",
        groq_api_key="test-key",
        groq_api_url="http://groq.example.com",
        library_info_path="data/library_info.json",
    )


@pytest.fixture
def _mock_library_info():
    return LibraryInfo(
        hours={"monday": "9-5"},
        policies={"borrowing_limit": "10"},
        fines={"overdue_per_day": "$0.25"},
    )


@pytest.mark.asyncio
async def test_startup_initialises_module_variables(_mock_settings, _mock_library_info):
    """Startup handler should populate settings, groq_client, session_manager, and library_info."""
    import app.main as main_module

    with (
        patch.object(main_module, "load_settings", return_value=_mock_settings),
        patch.object(main_module, "load_library_info", return_value=_mock_library_info),
        patch.object(main_module, "GroqClient") as mock_groq_cls,
    ):
        mock_groq_cls.return_value = MagicMock()

        await main_module.startup()

        assert main_module.settings is _mock_settings
        assert main_module.groq_client is mock_groq_cls.return_value
        assert main_module.session_manager is not None
        assert main_module.library_info is _mock_library_info
        mock_groq_cls.assert_called_once_with(api_key="test-key")


@pytest.mark.asyncio
async def test_startup_starts_cleanup_background_task(_mock_settings, _mock_library_info):
    """Startup should create an asyncio background task for periodic cleanup."""
    import app.main as main_module

    with (
        patch.object(main_module, "load_settings", return_value=_mock_settings),
        patch.object(main_module, "load_library_info", return_value=_mock_library_info),
        patch.object(main_module, "GroqClient", return_value=MagicMock()),
        patch("asyncio.create_task") as mock_create_task,
    ):
        await main_module.startup()
        mock_create_task.assert_called_once()


def test_cors_middleware_is_registered():
    """CORS middleware should be present in the app middleware stack."""
    from app.main import app

    middleware_classes = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" in middleware_classes
