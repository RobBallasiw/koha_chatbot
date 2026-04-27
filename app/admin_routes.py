"""Admin API endpoints for chat session monitoring."""

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.admin_auth import verify_admin_key
from app.models import (
    SessionDetail, SessionListResponse, SessionStatsResponse, AnalyticsResponse,
    FeedbackStats, FeedbackEntry, UnansweredQueueResponse, BulkCleanupResponse,
)
from app.session_store import SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/api", dependencies=[Depends(verify_admin_key)])

# Separate router for login (no auth required)
login_router = APIRouter(prefix="/admin/api")

session_store: SessionStore | None = None
library_info_path: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    api_key: str


def set_session_store(store: SessionStore) -> None:
    """Set the module-level SessionStore instance (called at app startup)."""
    global session_store
    session_store = store


def set_library_info_path(path: str) -> None:
    """Set the path to library_info.json (called at app startup)."""
    global library_info_path
    library_info_path = path


@login_router.post("/login", response_model=LoginResponse)
async def admin_login(request: LoginRequest):
    """Validate credentials and return the API key."""
    expected_user = os.environ.get("ADMIN_USERNAME", "admin")
    expected_pass = os.environ.get("ADMIN_PASSWORD", "admin")

    if request.username == expected_user and request.password == expected_pass:
        api_key = os.environ.get("ADMIN_API_KEY", "")
        if not api_key:
            raise HTTPException(status_code=500, detail={"error": "Admin API key not configured"})
        return LoginResponse(api_key=api_key)

    raise HTTPException(status_code=401, detail={"error": "Invalid username or password"})


@router.get("/verify")
async def verify_account():
    """Verify the current session is still valid.

    The X-Admin-Key header is validated by the router dependency.
    """
    return {"status": "ok"}


def _get_store() -> SessionStore:
    """Return the session store or raise 500 if not initialised."""
    global session_store
    if session_store is None:
        # Try to initialise on-demand (for serverless cold starts)
        import os
        db_path = os.environ.get("SESSION_DB_PATH", "/tmp/sessions.db")
        try:
            session_store = SessionStore(db_path=db_path)
        except Exception:
            raise HTTPException(status_code=500, detail={"error": "Unable to retrieve session data"})
    return session_store


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> SessionListResponse:
    """Return a paginated list of chat sessions."""
    store = _get_store()

    # Clamp invalid pagination params to defaults
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20

    # Ignore empty search keyword
    if search is not None and not search.strip():
        search = None

    try:
        return store.get_sessions(page=page, page_size=page_size, status=status, search=search)
    except Exception:
        logger.exception("Failed to retrieve sessions")
        return JSONResponse(
            status_code=500,
            content={"error": "Unable to retrieve session data"},
        )


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str) -> SessionDetail:
    """Return full detail for a single chat session."""
    store = _get_store()

    try:
        detail = store.get_session(session_id)
    except Exception:
        logger.exception("Failed to retrieve session %s", session_id)
        return JSONResponse(
            status_code=500,
            content={"error": "Unable to retrieve session data"},
        )

    if detail is None:
        return JSONResponse(status_code=404, content={"error": "Session not found"})

    return detail


@router.get("/stats", response_model=SessionStatsResponse)
async def get_stats() -> SessionStatsResponse:
    """Return aggregate session statistics."""
    store = _get_store()

    try:
        return store.get_stats()
    except Exception:
        logger.exception("Failed to retrieve session stats")
        return JSONResponse(
            status_code=500,
            content={"error": "Unable to retrieve session data"},
        )


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    days: int = Query(default=30, ge=1, le=365),
) -> AnalyticsResponse:
    """Return analytics data for the admin dashboard."""
    store = _get_store()

    try:
        return store.get_analytics(days=days)
    except Exception:
        logger.exception("Failed to retrieve analytics")
        return JSONResponse(
            status_code=500,
            content={"error": "Unable to retrieve analytics data"},
        )


@router.get("/quality/feedback-stats", response_model=FeedbackStats)
async def get_feedback_stats(
    days: int = Query(default=30, ge=1, le=365),
) -> FeedbackStats:
    """Return aggregate patron feedback statistics."""
    store = _get_store()
    try:
        return store.get_feedback_stats(days=days)
    except Exception:
        logger.exception("Failed to retrieve feedback stats")
        return JSONResponse(
            status_code=500,
            content={"error": "Unable to retrieve feedback data"},
        )


@router.get("/quality/feedback", response_model=list[FeedbackEntry])
async def get_recent_feedback(
    days: int = Query(default=30, ge=1, le=365),
    rating: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> list[FeedbackEntry]:
    """Return recent feedback entries with message context."""
    store = _get_store()
    try:
        return store.get_recent_feedback(
            days=days, rating_filter=rating, page=page, page_size=page_size,
        )
    except Exception:
        logger.exception("Failed to retrieve feedback")
        return JSONResponse(
            status_code=500,
            content={"error": "Unable to retrieve feedback data"},
        )


@router.get("/quality/unanswered", response_model=UnansweredQueueResponse)
async def get_unanswered_queries(
    days: int = Query(default=30, ge=1, le=365),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> UnansweredQueueResponse:
    """Return unanswered/failed patron queries for review."""
    store = _get_store()
    try:
        return store.get_unanswered_queries(
            days=days, page=page, page_size=page_size,
        )
    except Exception:
        logger.exception("Failed to retrieve unanswered queries")
        return JSONResponse(
            status_code=500,
            content={"error": "Unable to retrieve unanswered queries"},
        )


# ------------------------------------------------------------------
# Library Info Management
# ------------------------------------------------------------------


@router.get("/library-info")
async def get_library_info():
    """Return the current library info contents (from DB or file)."""
    # Try database first (works on Vercel)
    from app.staff_routes import staff_store as _staff_store
    if _staff_store is not None:
        db_val = _staff_store.get_setting("library_info_json")
        if db_val:
            try:
                return json.loads(db_val)
            except Exception:
                pass
    # Fall back to file
    if not library_info_path:
        return JSONResponse(status_code=500, content={"error": "Library info path not configured"})
    try:
        with open(library_info_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        logger.exception("Failed to read library info")
        return JSONResponse(status_code=500, content={"error": "Failed to read library info"})


@router.put("/library-info")
async def update_library_info(payload: dict):
    """Update library info and reload it in the running app."""
    # Validate structure
    if "locations" not in payload or not isinstance(payload["locations"], dict):
        return JSONResponse(status_code=400, content={"error": "Missing or invalid 'locations'."})
    for loc_name, loc_data in payload["locations"].items():
        if not isinstance(loc_data, dict):
            return JSONResponse(status_code=400, content={"error": f"Location '{loc_name}' must be an object."})
        if "hours" not in loc_data or not isinstance(loc_data["hours"], dict):
            return JSONResponse(status_code=400, content={"error": f"Location '{loc_name}' missing 'hours'."})
    for key in ("policies", "fines"):
        if key not in payload or not isinstance(payload[key], dict):
            return JSONResponse(status_code=400, content={"error": f"Missing or invalid '{key}' section."})

    # Save to database (works on Vercel and locally)
    from app.staff_routes import staff_store as _staff_store
    if _staff_store is not None:
        try:
            _staff_store.update_settings({"library_info_json": json.dumps(payload, ensure_ascii=False)})
        except Exception:
            logger.exception("Failed to save library info to database")
            return JSONResponse(status_code=500, content={"error": "Failed to save library info"})

    # Also try to write to file (works locally, fails silently on Vercel)
    if library_info_path:
        try:
            with open(library_info_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
        except Exception:
            logger.info("Could not write library_info.json to disk (read-only filesystem)")

    # Reload in the running app
    try:
        import app.main as main_module
        from app.library_info_handler import load_library_info
        from app.models import LibraryInfo
        main_module.library_info = LibraryInfo(**payload)
    except Exception:
        logger.exception("Failed to reload library info into running app")

    return {"status": "ok", "message": "Library info updated and reloaded"}


# ------------------------------------------------------------------
# Session Flagging
# ------------------------------------------------------------------


class FlagRequest(BaseModel):
    note: str = ""


@router.post("/sessions/{session_id}/flag")
async def flag_session(session_id: str, request: FlagRequest):
    """Flag a session with an optional note."""
    store = _get_store()
    try:
        store.flag_session(session_id, request.note)
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to flag session %s", session_id)
        return JSONResponse(status_code=500, content={"error": "Failed to flag session"})


@router.delete("/sessions/{session_id}/flag")
async def unflag_session(session_id: str):
    """Remove a flag from a session."""
    store = _get_store()
    try:
        store.unflag_session(session_id)
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to unflag session %s", session_id)
        return JSONResponse(status_code=500, content={"error": "Failed to unflag session"})


@router.get("/sessions/{session_id}/flag")
async def get_session_flag(session_id: str):
    """Get the flag for a session."""
    store = _get_store()
    try:
        flag = store.get_session_flag(session_id)
        if flag is None:
            return {"flagged": False}
        return {"flagged": True, "note": flag.note, "created_at": flag.created_at}
    except Exception:
        logger.exception("Failed to get flag for session %s", session_id)
        return JSONResponse(status_code=500, content={"error": "Failed to get session flag"})


@router.get("/flagged-sessions")
async def get_flagged_sessions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Return paginated list of flagged sessions."""
    store = _get_store()
    try:
        return store.get_flagged_sessions(page=page, page_size=page_size)
    except Exception:
        logger.exception("Failed to retrieve flagged sessions")
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve flagged sessions"})


# ------------------------------------------------------------------
# CSV Export
# ------------------------------------------------------------------


@router.get("/export/csv")
async def export_csv(
    status: str | None = Query(default=None),
    days: int | None = Query(default=None, ge=1, le=365),
):
    """Export sessions as a CSV file download."""
    store = _get_store()
    try:
        csv_content = store.export_sessions_csv(status=status, days=days)
        # Add UTF-8 BOM so Excel and other apps detect encoding correctly
        csv_bytes = b"\xef\xbb\xbf" + csv_content.encode("utf-8")
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=sessions_export.csv"},
        )
    except Exception:
        logger.exception("Failed to export sessions")
        return JSONResponse(status_code=500, content={"error": "Failed to export sessions"})


# ------------------------------------------------------------------
# Bulk Cleanup
# ------------------------------------------------------------------


@router.delete("/cleanup", response_model=BulkCleanupResponse)
async def bulk_cleanup(
    older_than_days: int = Query(default=30, ge=1, le=365),
) -> BulkCleanupResponse:
    """Delete expired sessions older than the specified number of days."""
    store = _get_store()
    try:
        return store.bulk_delete_expired(older_than_days=older_than_days)
    except Exception:
        logger.exception("Failed to perform bulk cleanup")
        return JSONResponse(status_code=500, content={"error": "Failed to perform cleanup"})


@router.delete("/cleanup/all", response_model=BulkCleanupResponse)
async def delete_all_sessions() -> BulkCleanupResponse:
    """Delete ALL sessions and associated data."""
    store = _get_store()
    try:
        return store.delete_all_sessions()
    except Exception:
        logger.exception("Failed to delete all sessions")
        return JSONResponse(status_code=500, content={"error": "Failed to delete all sessions"})


# ------------------------------------------------------------------
# Librarian Handoff (Talk to a Librarian)
# ------------------------------------------------------------------


class AdminReplyRequest(BaseModel):
    message: str
    sender_name: str = ""


@router.get("/handoff-sessions")
async def get_handoff_sessions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Return live chat sessions waiting for or active with a librarian."""
    store = _get_store()
    try:
        return store.get_waiting_live_chats(page=page, page_size=page_size)
    except Exception:
        logger.exception("Failed to retrieve handoff sessions")
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve handoff sessions"})


@router.post("/live-chat/{live_chat_id}/reply")
async def live_chat_reply(live_chat_id: str, request: AdminReplyRequest):
    """Send a librarian reply to a live chat session."""
    store = _get_store()
    if not request.message or not request.message.strip():
        return JSONResponse(status_code=400, content={"error": "Message is required"})
    try:
        store.save_live_chat_message(live_chat_id, "librarian", request.message.strip())
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to save reply for live chat %s", live_chat_id)
        return JSONResponse(status_code=500, content={"error": "Failed to send reply"})


@router.post("/sessions/{session_id}/reply")
async def admin_reply(session_id: str, request: AdminReplyRequest):
    """Send a librarian reply — routes to live chat if one exists."""
    store = _get_store()
    if not request.message or not request.message.strip():
        return JSONResponse(status_code=400, content={"error": "Message is required"})
    try:
        # Check for active live chat and route there
        live_chat = store.get_active_live_chat(session_id)
        if live_chat:
            store.save_live_chat_message(live_chat["id"], "librarian", request.message.strip())
        else:
            store.save_message(session_id, "librarian", request.message.strip())
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to save admin reply for session %s", session_id)
        return JSONResponse(status_code=500, content={"error": "Failed to send reply"})


class ClaimRequest(BaseModel):
    username: str


@router.post("/live-chat/{live_chat_id}/claim")
async def claim_live_chat(live_chat_id: str, request: ClaimRequest):
    """Claim a live chat session."""
    store = _get_store()
    if not request.username or not request.username.strip():
        return JSONResponse(status_code=400, content={"error": "Username is required"})
    try:
        result = store.claim_live_chat(live_chat_id, request.username.strip())
        if not result["ok"]:
            return JSONResponse(status_code=409, content=result)
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to claim live chat %s", live_chat_id)
        return JSONResponse(status_code=500, content={"error": "Failed to claim session"})


@router.post("/sessions/{session_id}/claim")
async def claim_handoff(session_id: str, request: ClaimRequest):
    """Claim a handoff session — routes to live chat if one exists."""
    store = _get_store()
    if not request.username or not request.username.strip():
        return JSONResponse(status_code=400, content={"error": "Username is required"})
    try:
        live_chat = store.get_active_live_chat(session_id)
        if live_chat:
            result = store.claim_live_chat(live_chat["id"], request.username.strip())
        else:
            result = store.claim_handoff(session_id, request.username.strip())
        if not result["ok"]:
            return JSONResponse(status_code=409, content=result)
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to claim handoff for session %s", session_id)
        return JSONResponse(status_code=500, content={"error": "Failed to claim session"})


@router.post("/live-chat/{live_chat_id}/release")
async def release_live_chat(live_chat_id: str):
    """Release a claimed live chat session."""
    store = _get_store()
    try:
        store.release_live_chat(live_chat_id)
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to release live chat %s", live_chat_id)
        return JSONResponse(status_code=500, content={"error": "Failed to release session"})


@router.post("/sessions/{session_id}/release")
async def release_handoff(session_id: str):
    """Release a claimed handoff session."""
    store = _get_store()
    try:
        live_chat = store.get_active_live_chat(session_id)
        if live_chat:
            store.release_live_chat(live_chat["id"])
        else:
            store.release_handoff(session_id)
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to release handoff for session %s", session_id)
        return JSONResponse(status_code=500, content={"error": "Failed to release session"})


@router.post("/live-chat/{live_chat_id}/end")
async def end_live_chat(live_chat_id: str):
    """End a live chat session."""
    store = _get_store()
    try:
        store.end_live_chat(live_chat_id)
        # Save a "Hero is back" message on the parent session
        conn = store._get_connection()
        try:
            row = conn.execute(
                "SELECT parent_session_id FROM live_chat_sessions WHERE id = ?",
                (live_chat_id,),
            ).fetchone()
            if row:
                store.save_message(row["parent_session_id"], "assistant",
                    "The librarian has ended the chat. I'm Hero, back to help! 👋 What else can I do for you?")
        finally:
            conn.close()
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to end live chat %s", live_chat_id)
        return JSONResponse(status_code=500, content={"error": "Failed to end live chat"})


@router.get("/live-chat/{live_chat_id}/messages")
async def get_live_chat_messages(live_chat_id: str):
    """Return all messages and status for a live chat session."""
    store = _get_store()
    try:
        messages = store.get_all_live_chat_messages(live_chat_id)
        # Get status
        conn = store._get_connection()
        try:
            row = conn.execute(
                "SELECT status FROM live_chat_sessions WHERE id = ?",
                (live_chat_id,),
            ).fetchone()
            status = row["status"] if row else "ended"
        finally:
            conn.close()
        return {"messages": messages, "status": status}
    except Exception:
        logger.exception("Failed to get messages for live chat %s", live_chat_id)
        return JSONResponse(status_code=500, content={"error": "Failed to get messages"})


@router.post("/sessions/{session_id}/end-handoff")
async def end_handoff(session_id: str):
    """End the librarian handoff — routes to live chat if one exists."""
    store = _get_store()
    try:
        live_chat = store.get_active_live_chat(session_id)
        if live_chat:
            store.end_live_chat(live_chat["id"])
        else:
            store.deactivate_handoff(session_id)
        store.save_message(session_id, "assistant",
            "The librarian has ended the chat. I'm Hero, back to help! 👋 What else can I do for you?")
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to end handoff for session %s", session_id)
        return JSONResponse(status_code=500, content={"error": "Failed to end handoff"})


# ------------------------------------------------------------------
# Notify Staff (send email to a specific librarian)
# ------------------------------------------------------------------


class NotifyStaffRequest(BaseModel):
    name: str
    email: str
    session_id: str = ""


@router.post("/notify-staff")
async def notify_staff(request: NotifyStaffRequest):
    """Send a notification email to a specific librarian to join live chat."""
    if not request.name or not request.name.strip():
        return JSONResponse(status_code=400, content={"error": "Staff name is required"})
    if not request.email or not request.email.strip():
        return JSONResponse(status_code=400, content={"error": "Email address is required"})

    smtp_email = os.environ.get("SMTP_EMAIL", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    has_service_account = bool(
        os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    )
    if not smtp_email or (not smtp_password and not has_service_account):
        return JSONResponse(status_code=500, content={"error": "Email is not configured. Set SMTP_EMAIL and either a service account or SMTP_PASSWORD."})

    chatbot_url = os.environ.get("CHATBOT_PUBLIC_URL", "http://localhost:8000")
    from app.email_notify import send_staff_notify_email
    try:
        ok = send_staff_notify_email(
            smtp_email=smtp_email,
            smtp_password=smtp_password,
            recipient_email=request.email.strip(),
            staff_name=request.name.strip(),
            session_id=request.session_id.strip() if request.session_id else "",
            admin_url=chatbot_url,
        )
        if ok:
            return {"status": "ok", "message": f"Notification sent to {request.name}"}
        return JSONResponse(status_code=500, content={"error": "Failed to send email"})
    except Exception:
        logger.exception("Failed to send staff notification to %s", request.email)
        return JSONResponse(status_code=500, content={"error": "Failed to send email"})


class TestEmailRequest(BaseModel):
    email: str


@router.post("/test-email")
async def test_email(request: TestEmailRequest):
    """Send a test email to verify SMTP configuration works."""
    if not request.email or not request.email.strip():
        return JSONResponse(status_code=400, content={"error": "Email is required"})
    smtp_email = os.environ.get("SMTP_EMAIL", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    chatbot_url = os.environ.get("CHATBOT_PUBLIC_URL", "http://localhost:8000")
    from app.email_notify import send_staff_notify_email
    try:
        ok = send_staff_notify_email(
            smtp_email=smtp_email,
            smtp_password=smtp_password,
            recipient_email=request.email.strip(),
            staff_name="Test",
            session_id="test-session-123",
            admin_url=chatbot_url,
        )
        if ok:
            return {"status": "ok", "message": f"Test email sent to {request.email}"}
        return JSONResponse(status_code=500, content={"error": "Email send failed — check SMTP_EMAIL and SMTP_PASSWORD"})
    except Exception as e:
        logger.exception("Test email failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ------------------------------------------------------------------
# Staff Ratings
# ------------------------------------------------------------------


@router.get("/staff-ratings")
async def get_staff_ratings(
    days: int = Query(default=30, ge=1, le=365),
):
    """Return per-staff rating summary."""
    store = _get_store()
    try:
        return store.get_staff_ratings_summary(days=days)
    except Exception:
        logger.exception("Failed to retrieve staff ratings")
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve staff ratings"})


@router.get("/staff-ratings/{staff_username}")
async def get_staff_rating_details(
    staff_username: str,
    days: int = Query(default=30, ge=1, le=365),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Return individual rating entries for a specific staff member."""
    store = _get_store()
    try:
        return store.get_staff_rating_details(
            staff_username=staff_username, days=days, page=page, page_size=page_size,
        )
    except Exception:
        logger.exception("Failed to retrieve ratings for staff %s", staff_username)
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve staff ratings"})


# ------------------------------------------------------------------
# Handoff Archive (completed live chat sessions)
# ------------------------------------------------------------------


@router.get("/handoff-archive")
async def get_handoff_archive(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    staff: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
):
    """Return archived (completed) handoff sessions with staff name and rating."""
    store = _get_store()
    try:
        return store.get_handoff_archive(page=page, page_size=page_size, staff=staff, days=days)
    except Exception:
        logger.exception("Failed to retrieve handoff archive")
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve handoff archive"})


@router.get("/sessions/{session_id}/handoff-messages")
async def get_handoff_messages(
    session_id: str,
    handoff_num: int = Query(default=0, ge=0),
):
    """Return only the handoff portion of a session's messages."""
    store = _get_store()
    try:
        messages = store.get_handoff_messages(session_id, handoff_num=handoff_num)
        return {"messages": messages}
    except Exception:
        logger.exception("Failed to retrieve handoff messages for session %s", session_id)
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve messages"})


@router.delete("/handoff-archive/{rating_id}")
async def delete_handoff_record(rating_id: int):
    """Delete a single handoff rating record."""
    store = _get_store()
    try:
        deleted = store.delete_handoff_record(rating_id)
        if not deleted:
            return JSONResponse(status_code=404, content={"error": "Record not found"})
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to delete handoff record %s", rating_id)
        return JSONResponse(status_code=500, content={"error": "Failed to delete record"})


@router.delete("/handoff-archive")
async def delete_all_handoff_records(
    days: int = Query(default=0, ge=0, le=365),
):
    """Delete all handoff records. If days > 0, only older than that."""
    store = _get_store()
    try:
        result = store.delete_all_handoff_records(days=days)
        return result
    except Exception:
        logger.exception("Failed to delete handoff records")
        return JSONResponse(status_code=500, content={"error": "Failed to delete records"})


# ------------------------------------------------------------------
# Live Chat History
# ------------------------------------------------------------------


@router.get("/live-chat-history")
async def get_live_chat_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    staff: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
):
    """Return completed live chat sessions."""
    store = _get_store()
    try:
        return store.get_live_chat_history(page=page, page_size=page_size, staff=staff, days=days)
    except Exception:
        logger.exception("Failed to retrieve live chat history")
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve live chat history"})


@router.delete("/live-chat-history")
async def delete_live_chat_history(
    days: int = Query(default=0, ge=0, le=365),
):
    """Delete ended live chat sessions. If days > 0, only older than that."""
    store = _get_store()
    try:
        result = store.delete_live_chat_history(days=days)
        return result
    except Exception:
        logger.exception("Failed to delete live chat history")
        return JSONResponse(status_code=500, content={"error": "Failed to delete live chat history"})
