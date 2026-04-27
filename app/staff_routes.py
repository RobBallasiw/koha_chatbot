"""Dashboard settings, notification emails, and staff contact API endpoints."""

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
        db_path = os.environ.get("SESSION_DB_PATH", "/tmp/sessions.db")
        try:
            staff_store = StaffStore(db_path=db_path)
        except Exception:
            raise HTTPException(status_code=500, detail={"error": "Settings store not initialised"})
    return staff_store


# ------------------------------------------------------------------
# Dashboard settings
# ------------------------------------------------------------------

class UpdateSettingsRequest(BaseModel):
    settings: dict[str, str]


@router.get("/settings")
async def get_settings():
    store = _get_store()
    return store.get_all_settings()


@router.put("/settings")
async def update_settings(request: UpdateSettingsRequest):
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
# Notification email management (legacy — kept for backward compat)
# ------------------------------------------------------------------

@router.get("/notification-emails")
async def get_notification_emails():
    store = _get_store()
    raw = store.get_setting("notification_emails")
    if raw:
        try:
            return {"emails": json.loads(raw)}
        except Exception:
            pass
    env_email = os.environ.get("LIBRARIAN_EMAIL", "")
    return {"emails": [env_email] if env_email else []}


class NotificationEmailsRequest(BaseModel):
    emails: list[str]


@router.put("/notification-emails")
async def update_notification_emails(request: NotificationEmailsRequest):
    store = _get_store()
    cleaned = [e.strip() for e in request.emails if e.strip()]
    try:
        store.update_settings({"notification_emails": json.dumps(cleaned)})
        return {"status": "ok", "emails": cleaned}
    except Exception:
        logger.exception("Failed to update notification emails")
        return JSONResponse(status_code=500, content={"error": "Failed to update emails"})


# ------------------------------------------------------------------
# Staff contacts (name + email for live chat notifications)
# ------------------------------------------------------------------

class CreateContactRequest(BaseModel):
    name: str
    email: str


class UpdateContactRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    is_active: bool | None = None


@router.get("/staff-contacts")
async def list_contacts():
    """Return all staff contacts."""
    store = _get_store()
    return store.list_contacts()


@router.post("/staff-contacts")
async def create_contact(request: CreateContactRequest):
    """Add a new staff contact."""
    store = _get_store()
    if not request.name or not request.name.strip():
        return JSONResponse(status_code=400, content={"error": "Name is required"})
    if not request.email or not request.email.strip():
        return JSONResponse(status_code=400, content={"error": "Email is required"})
    try:
        contact = store.add_contact(name=request.name, email=request.email)
        return {"status": "ok", "contact": contact}
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": str(e)})
    except Exception:
        logger.exception("Failed to create staff contact")
        return JSONResponse(status_code=500, content={"error": "Failed to create contact"})


@router.put("/staff-contacts/{contact_id}")
async def update_contact(contact_id: int, request: UpdateContactRequest):
    """Update a staff contact."""
    store = _get_store()
    try:
        updated = store.update_contact(
            contact_id=contact_id,
            name=request.name,
            email=request.email,
            is_active=request.is_active,
        )
        if not updated:
            return JSONResponse(status_code=404, content={"error": "Contact not found"})
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to update contact %s", contact_id)
        return JSONResponse(status_code=500, content={"error": "Failed to update contact"})


@router.delete("/staff-contacts/{contact_id}")
async def delete_contact(contact_id: int):
    """Delete a staff contact."""
    store = _get_store()
    try:
        deleted = store.delete_contact(contact_id)
        if not deleted:
            return JSONResponse(status_code=404, content={"error": "Contact not found"})
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to delete contact %s", contact_id)
        return JSONResponse(status_code=500, content={"error": "Failed to delete contact"})
