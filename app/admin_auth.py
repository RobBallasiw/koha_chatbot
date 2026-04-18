"""Admin authentication dependency — validates X-Admin-Key header."""

from fastapi import Header, HTTPException


def get_admin_api_key() -> str | None:
    """Return the configured admin API key from settings.

    Returns None if the key is not configured, which causes all
    admin requests to be rejected with 401.
    """
    from app.config import load_settings

    try:
        settings = load_settings()
    except SystemExit:
        return None
    return settings.admin_api_key


def verify_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency that enforces admin API key authentication.

    Raises HTTPException 401 when:
    - The X-Admin-Key header is missing
    - The provided key does not match the configured ADMIN_API_KEY
    - The ADMIN_API_KEY environment variable is not set
    """
    expected = get_admin_api_key()

    if not x_admin_key:
        raise HTTPException(status_code=401, detail={"error": "Admin API key is required"})

    if not expected or x_admin_key != expected:
        raise HTTPException(status_code=401, detail={"error": "Invalid admin API key"})
