"""Dashboard settings and notification email API endpoints."""

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.admin_auth import verify_admin_key
from app.staff_store import StaffStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/api", dependencies=[Depends(verify_admin_key)])

staff_store: StaffStore | None = None


def set_staff_store(store: StaffStore) -> None:
    """Set the module-level StaffStore instance (called at app startup)."""
    global staff_store
    staff_store = store


def _get_store() -> StaffStore:
    global staff_store
    if staff_store is None:
        # Try to initialise on-demand (for serverless cold starts)
        db_path = os.environ.get("SESSION_DB_PATH", "/tmp/sessions.db")
        try:
            staff_store = StaffStore(db_path=db_path)
        except Exception:
            raise HTTPException(status_code=500, detail={"error": "Settings store not initialised"})
    return staff_store


# ------------------------------------------------------------------
# Dashboard settings models
# ------------------------------------------------------------------

class UpdateSettingsRequest(BaseModel):
    settings: dict[str, str]


# ------------------------------------------------------------------
# Dashboard settings endpoints
# ------------------------------------------------------------------

@router.get("/settings")
async def get_settings():
    """Return all dashboard settings."""
    store = _get_store()
    return store.get_all_settings()


@router.put("/settings")
async def update_settings(request: UpdateSettingsRequest):
    """Update one or more dashboard settings."""
    store = _get_store()
    if not request.settings:
        return JSONResponse(status_code=400, content={"error": "No settings provided"})
    try:
        store.update_settings(request.settings)
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to update settings")
        return JSONResponse(status_code=500, content={"error": "Failed to update settings"})


# ------------------------------------------------------------------
# Notification email management
# ------------------------------------------------------------------

@router.get("/notification-emails")
async def get_notification_emails():
    """Return the list of notification emails."""
    store = _get_store()
    raw = store.get_setting("notification_emails")
    if raw:
        try:
            return {"emails": json.loads(raw)}
        except Exception:
            pass
    # Fall back to env var
    env_email = os.environ.get("LIBRARIAN_EMAIL", "")
    return {"emails": [env_email] if env_email else []}


class NotificationEmailsRequest(BaseModel):
    emails: list[str]


@router.put("/notification-emails")
async def update_notification_emails(request: NotificationEmailsRequest):
    """Update the list of notification emails."""
    store = _get_store()
    # Filter out empty strings and strip whitespace
    cleaned = [e.strip() for e in request.emails if e.strip()]
    try:
        store.update_settings({"notification_emails": json.dumps(cleaned)})
        return {"status": "ok", "emails": cleaned}
    except Exception:
        logger.exception("Failed to update notification emails")
        return JSONResponse(status_code=500, content={"error": "Failed to update emails"})
