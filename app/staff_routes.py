"""Staff account management and dashboard settings API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
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
        import os
        db_path = os.environ.get("SESSION_DB_PATH", "/tmp/sessions.db")
        try:
            staff_store = StaffStore(db_path=db_path)
        except Exception:
            raise HTTPException(status_code=500, detail={"error": "Staff store not initialised"})
    return staff_store


# ------------------------------------------------------------------
# Staff account models
# ------------------------------------------------------------------

class CreateStaffRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "staff"


class UpdateStaffRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str


class UpdateSettingsRequest(BaseModel):
    settings: dict[str, str]


# ------------------------------------------------------------------
# Staff CRUD endpoints
# ------------------------------------------------------------------

@router.get("/staff")
async def list_staff():
    """Return all staff accounts."""
    store = _get_store()
    return store.list_staff()


@router.post("/staff")
async def create_staff(request: CreateStaffRequest):
    """Create a new staff account."""
    store = _get_store()
    if not request.username or not request.username.strip():
        return JSONResponse(status_code=400, content={"error": "Username is required"})
    if not request.password or len(request.password) < 4:
        return JSONResponse(status_code=400, content={"error": "Password must be at least 4 characters"})
    if request.role not in ("admin", "staff"):
        return JSONResponse(status_code=400, content={"error": "Role must be 'admin' or 'staff'"})
    try:
        account = store.create_staff(
            username=request.username,
            password=request.password,
            display_name=request.display_name,
            role=request.role,
        )
        return {"status": "ok", "account": account}
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": str(e)})
    except Exception:
        logger.exception("Failed to create staff account")
        return JSONResponse(status_code=500, content={"error": "Failed to create account"})


@router.put("/staff/{staff_id}")
async def update_staff(staff_id: int, request: UpdateStaffRequest):
    """Update a staff account's display name, role, or active status."""
    store = _get_store()
    if request.role is not None and request.role not in ("admin", "staff"):
        return JSONResponse(status_code=400, content={"error": "Role must be 'admin' or 'staff'"})
    try:
        updated = store.update_staff(
            staff_id=staff_id,
            display_name=request.display_name,
            role=request.role,
            is_active=request.is_active,
        )
        if not updated:
            return JSONResponse(status_code=404, content={"error": "Staff account not found"})
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to update staff account %s", staff_id)
        return JSONResponse(status_code=500, content={"error": "Failed to update account"})


@router.post("/staff/{staff_id}/reset-password")
async def reset_password(staff_id: int, request: ResetPasswordRequest):
    """Reset a staff member's password."""
    store = _get_store()
    if not request.new_password or len(request.new_password) < 4:
        return JSONResponse(status_code=400, content={"error": "Password must be at least 4 characters"})
    try:
        updated = store.reset_password(staff_id, request.new_password)
        if not updated:
            return JSONResponse(status_code=404, content={"error": "Staff account not found"})
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to reset password for staff %s", staff_id)
        return JSONResponse(status_code=500, content={"error": "Failed to reset password"})


@router.delete("/staff/{staff_id}")
async def delete_staff(staff_id: int):
    """Permanently delete a staff account."""
    store = _get_store()
    try:
        deleted = store.delete_staff(staff_id)
        if not deleted:
            return JSONResponse(status_code=404, content={"error": "Staff account not found"})
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to delete staff account %s", staff_id)
        return JSONResponse(status_code=500, content={"error": "Failed to delete account"})


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
# Per-staff settings endpoints
# ------------------------------------------------------------------

@router.get("/staff/{staff_id}/settings")
async def get_staff_settings(staff_id: int):
    """Return merged settings for a specific staff member (global + overrides)."""
    store = _get_store()
    return store.get_staff_settings(staff_id)


@router.put("/staff/{staff_id}/settings")
async def update_staff_settings(staff_id: int, request: UpdateSettingsRequest):
    """Update per-staff settings (overrides global defaults)."""
    store = _get_store()
    if not request.settings:
        return JSONResponse(status_code=400, content={"error": "No settings provided"})
    try:
        store.update_staff_settings(staff_id, request.settings)
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to update staff settings for %s", staff_id)
        return JSONResponse(status_code=500, content={"error": "Failed to update settings"})


# ------------------------------------------------------------------
# Notification email management
# ------------------------------------------------------------------


@router.get("/notification-emails")
async def get_notification_emails():
    """Return the list of notification emails."""
    import json
    store = _get_store()
    raw = store.get_setting("notification_emails")
    if raw:
        try:
            return {"emails": json.loads(raw)}
        except Exception:
            pass
    # Fall back to env var
    import os
    env_email = os.environ.get("LIBRARIAN_EMAIL", "")
    return {"emails": [env_email] if env_email else []}


class NotificationEmailsRequest(BaseModel):
    emails: list[str]


@router.put("/notification-emails")
async def update_notification_emails(request: NotificationEmailsRequest):
    """Update the list of notification emails."""
    import json
    store = _get_store()
    # Filter out empty strings and strip whitespace
    cleaned = [e.strip() for e in request.emails if e.strip()]
    try:
        store.update_settings({"notification_emails": json.dumps(cleaned)})
        return {"status": "ok", "emails": cleaned}
    except Exception:
        logger.exception("Failed to update notification emails")
        return JSONResponse(status_code=500, content={"error": "Failed to update emails"})
