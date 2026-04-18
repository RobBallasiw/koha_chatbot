"""Main FastAPI application — chat endpoint and request routing."""

import asyncio
import logging
import os
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.admin_routes import router as admin_router, login_router as admin_login_router, set_session_store, set_library_info_path
from app.catalog_handler import handle_catalog_query
from app.config import Settings, load_settings
from app.groq_client import GroqClient
from app.library_info_handler import handle_library_info_query, load_library_info
from app.models import ChatRequest, ChatResponse, ErrorResponse, LibraryInfo
from app.models import FeedbackRequest
from pydantic import BaseModel
from app.query_classifier import classify_query
from app.session_manager import SessionManager
from app.session_store import SessionStore
from app.staff_routes import router as staff_router, set_staff_store
from app.staff_store import StaffStore

app = FastAPI(title="Library AI Chatbot")

# CORS middleware for iframe embedding from any Koha instance.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount admin API routers.
app.include_router(admin_login_router)
app.include_router(admin_router)
app.include_router(staff_router)

# Module-level variables initialised during the startup event.
settings: Settings | None = None
groq_client: GroqClient | None = None
session_manager: SessionManager | None = None
session_store: SessionStore | None = None
library_info: LibraryInfo | None = None

CLARIFYING_MESSAGE = (
    "Hmm, I'm not quite sure what you mean! 🤔 "
    "I'm Hero, your library assistant — I can help you with:\n"
    "📚 Finding books in the catalog\n"
    "🕐 Library hours and locations\n"
    "📋 Policies, fines, and membership info\n\n"
    "What would you like to know?"
)

GREETING_MESSAGE = (
    "Hey there! 👋 I'm Hero, your library assistant. "
    "I can help you find books, check library hours, or answer questions about policies and fines. "
    "What can I do for you?"
)

HANDOFF_ACTIVATED_MESSAGE = (
    "I've notified a librarian — they'll join this chat shortly! 📨\n"
    "Feel free to keep typing your question here and they'll see it."
)

HANDOFF_ACTIVE_NOTE = (
    "A librarian has been notified and will respond here soon. "
    "Your message has been saved. 💬"
)

# Cleanup interval for expired sessions (seconds).
_CLEANUP_INTERVAL = 300


async def _periodic_cleanup(mgr: SessionManager) -> None:
    """Run session cleanup in an infinite loop, sleeping between runs."""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL)
        mgr.cleanup_expired()


@app.on_event("startup")
async def startup() -> None:
    """Initialise application state on startup."""
    global settings, groq_client, session_manager, session_store, library_info

    try:
        settings = load_settings()
    except Exception:
        logger.warning("Failed to load settings — using defaults")
        settings = None

    if settings:
        groq_client = GroqClient(
            base_url=settings.ollama_url,
            model=settings.ollama_model,
        )
    else:
        groq_client = None

    session_manager = SessionManager()

    if settings:
        library_info = load_library_info(settings.library_info_path)
    else:
        library_info = LibraryInfo()

    # Initialise persistent session store for admin monitoring.
    db_path = os.environ.get("SESSION_DB_PATH", "/tmp/sessions.db")
    try:
        session_store = SessionStore(db_path=db_path)
        set_session_store(session_store)
    except Exception:
        logger.warning("Failed to initialise session store at %s", db_path)
        session_store = None

    if settings:
        set_library_info_path(settings.library_info_path)

    # Initialise staff account and settings store.
    try:
        staff_store_instance = StaffStore(db_path=db_path)
        set_staff_store(staff_store_instance)
    except Exception:
        logger.warning("Failed to initialise staff store")

    # Background task that purges expired sessions every 5 minutes.
    asyncio.create_task(_periodic_cleanup(session_manager))


@app.get("/health")
async def health():
    """Simple health-check endpoint with debug info."""
    import os
    return {
        "status": "ok",
        "env_check": {
            "ADMIN_API_KEY": bool(os.environ.get("ADMIN_API_KEY")),
            "ADMIN_USERNAME": bool(os.environ.get("ADMIN_USERNAME")),
            "KOHA_API_URL": bool(os.environ.get("KOHA_API_URL")),
            "LIBRARY_INFO_PATH": bool(os.environ.get("LIBRARY_INFO_PATH")),
            "SESSION_DB_PATH": os.environ.get("SESSION_DB_PATH", "(default /tmp/sessions.db)"),
        },
        "session_store_ok": session_store is not None,
        "settings_ok": settings is not None,
    }


@app.get("/")
async def root():
    """Root endpoint — confirms the API is running."""
    return {"status": "ok", "app": "Library AI Chatbot"}


@app.get("/debug/test-store")
async def debug_test_store():
    """Debug endpoint to test if the session store works (no auth required)."""
    try:
        if session_store is None:
            return {"error": "session_store is None"}
        stats = session_store.get_stats()
        return {"ok": True, "stats": stats.model_dump() if hasattr(stats, 'model_dump') else str(stats)}
    except Exception as e:
        return {"ok": False, "error": str(e), "type": type(e).__name__}


@app.get("/debug/test-auth")
async def debug_test_auth():
    """Debug endpoint to test if admin auth works."""
    import os
    try:
        from app.admin_auth import get_admin_api_key
        key = get_admin_api_key()
        return {"ok": True, "key_set": bool(key)}
    except Exception as e:
        return {"ok": False, "error": str(e), "type": type(e).__name__}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Process a patron chat message and return a response.

    Validates the request, classifies the query intent, routes to the
    appropriate handler, and stores the conversation in the session.
    """
    global session_manager, groq_client, settings, library_info

    # --- Validate message ---
    if not request.message or not request.message.strip():
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="Message field is required and must be non-empty"
            ).model_dump(),
        )

    # --- Validate session_id ---
    if not request.session_id or not request.session_id.strip():
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="Session identifier is required"
            ).model_dump(),
        )

    # --- Session & history ---
    session_mgr = session_manager or SessionManager()
    history = session_mgr.get_history(request.session_id)

    # --- Check if handoff is active (librarian takeover) ---
    if session_store is not None and session_store.is_handoff_active(request.session_id):
        # Patron is in handoff mode — save their message silently, no bot reply
        session_mgr.add_message(request.session_id, "user", request.message)
        _store = session_store
        _sid = request.session_id
        _msg = request.message
        async def _persist_handoff():
            try:
                _store.save_message(_sid, "user", _msg, intent="handoff")
            except Exception:
                logger.exception("Failed to persist handoff message for session %s", _sid)
        asyncio.create_task(_persist_handoff())
        return ChatResponse(reply="", session_id=request.session_id, timestamp=time.time())

    # --- Classify intent ---
    client = groq_client  # may be None before startup wiring
    classification = classify_query(client, request.message, history)

    # --- Route to handler ---
    reply: str
    if classification.intent == "talk_to_librarian":
        # Check if handoff is already active — don't re-notify
        already_active = session_store is not None and session_store.is_handoff_active(request.session_id)
        if already_active:
            # Already in handoff — just save the message silently
            session_mgr.add_message(request.session_id, "user", request.message)
            if session_store is not None:
                _store = session_store
                _sid = request.session_id
                _msg = request.message
                async def _persist_dup():
                    try:
                        _store.save_message(_sid, "user", _msg, intent="handoff")
                    except Exception:
                        logger.exception("Failed to persist duplicate handoff msg for session %s", _sid)
                asyncio.create_task(_persist_dup())
            return ChatResponse(reply="", session_id=request.session_id, timestamp=time.time())

        # First time — activate handoff and notify
        reply = HANDOFF_ACTIVATED_MESSAGE
        if session_store is not None:
            try:
                # Save messages first (creates session row), then activate handoff
                session_store.save_message(request.session_id, "user", request.message, intent="talk_to_librarian")
                session_store.save_message(request.session_id, "assistant", reply)
                session_store.activate_handoff(request.session_id)
            except Exception:
                logger.exception("Failed to activate handoff for session %s", request.session_id)
        # Send notification in background (ntfy push or email)
        if settings:
            _cfg = settings
            _sid = request.session_id
            async def _send_notification():
                from app.email_notify import send_ntfy_notification, send_handoff_email
                if _cfg.ntfy_topic:
                    send_ntfy_notification(_cfg.ntfy_topic, _sid, _cfg.chatbot_public_url)
                elif _cfg.smtp_email and _cfg.smtp_password and _cfg.librarian_email:
                    send_handoff_email(
                        _cfg.smtp_email, _cfg.smtp_password, _cfg.librarian_email,
                        _sid, _cfg.chatbot_public_url,
                    )
            asyncio.create_task(_send_notification())
        session_mgr.add_message(request.session_id, "user", request.message)
        session_mgr.add_message(request.session_id, "assistant", reply)
        return ChatResponse(reply=reply, session_id=request.session_id, timestamp=time.time())
    elif classification.intent == "catalog_search":
        koha_url = settings.koha_api_url if settings else ""
        reply = await handle_catalog_query(
            client, request.message, koha_url, history
        )
    elif classification.intent == "library_info":
        reply = handle_library_info_query(
            client, request.message, library_info, history
        )
    elif classification.intent == "greeting":
        reply = GREETING_MESSAGE
    else:
        # "unclear" intent — ask for clarification
        reply = CLARIFYING_MESSAGE

    # --- Store conversation turn ---
    session_mgr.add_message(request.session_id, "user", request.message)
    session_mgr.add_message(request.session_id, "assistant", reply)

    # --- Persist to SQLite session store (non-blocking) ---
    if session_store is not None:
        _store = session_store
        _sid = request.session_id
        _msg = request.message
        _reply = reply
        _intent = classification.intent

        async def _persist():
            try:
                _store.save_message(_sid, "user", _msg, intent=_intent)
                _store.save_message(_sid, "assistant", _reply)
            except Exception:
                logger.exception("Failed to persist messages for session %s", _sid)

        asyncio.create_task(_persist())

    return ChatResponse(reply=reply, session_id=request.session_id, timestamp=time.time())


@app.post("/api/close-session")
async def close_session(request: ChatRequest):
    """Mark a chat session as expired when the patron closes the page."""
    if not request.session_id or not request.session_id.strip():
        return JSONResponse(status_code=400, content={"error": "Session identifier is required"})
    if session_store is not None:
        try:
            session_store.close_session(request.session_id)
        except Exception:
            logger.exception("Failed to close session %s", request.session_id)
    return {"status": "ok"}


@app.post("/api/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Accept patron feedback (thumbs up/down) on a bot response."""
    if not request.session_id or not request.session_id.strip():
        return JSONResponse(status_code=400, content={"error": "Session identifier is required"})
    if request.rating not in (1, -1):
        return JSONResponse(status_code=400, content={"error": "Rating must be 1 or -1"})
    if session_store is not None:
        try:
            session_store.save_feedback(
                request.session_id, request.message_timestamp, request.rating,
            )
        except Exception:
            logger.exception("Failed to save feedback for session %s", request.session_id)
            return JSONResponse(status_code=500, content={"error": "Failed to save feedback"})
    return {"status": "ok"}


class HandoffRatingRequest(BaseModel):
    session_id: str
    rating: int  # 1 = positive, -1 = negative


@app.post("/api/rate-handoff")
async def rate_handoff(request: HandoffRatingRequest):
    """Accept patron rating for the staff member who handled their live chat."""
    if not request.session_id or not request.session_id.strip():
        return JSONResponse(status_code=400, content={"error": "Session identifier is required"})
    if request.rating not in (1, -1):
        return JSONResponse(status_code=400, content={"error": "Rating must be 1 or -1"})
    if session_store is None:
        return JSONResponse(status_code=500, content={"error": "Store not available"})
    # Look up who handled this session
    claimed_by = session_store.get_handoff_claim(request.session_id)
    if not claimed_by:
        return JSONResponse(status_code=400, content={"error": "No staff handler found for this session"})
    try:
        session_store.save_staff_rating(request.session_id, claimed_by, request.rating)
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to save handoff rating for session %s", request.session_id)
        return JSONResponse(status_code=500, content={"error": "Failed to save rating"})


@app.get("/api/messenger-link")
async def get_messenger_link():
    """Return the configured Messenger link for the Talk to a Librarian feature."""
    link = settings.messenger_link if settings else "https://m.me/your-library-page"
    return {"messenger_link": link}


@app.get("/api/poll/{session_id}")
async def poll_messages(session_id: str, since: float = 0):
    """Patron polls for new messages (librarian replies) since a timestamp."""
    if session_store is None:
        return {"messages": [], "handoff_active": False, "handled_by": None}
    try:
        msgs = session_store.get_new_messages_since(session_id, since)
        handoff = session_store.is_handoff_active(session_id)
        claimed = session_store.get_handoff_claim(session_id)
        return {"messages": msgs, "handoff_active": handoff, "handled_by": claimed}
    except Exception:
        logger.exception("Failed to poll messages for session %s", session_id)
        return {"messages": [], "handoff_active": False, "handled_by": None}


# Serve admin dashboard HTML at /admin/.
_admin_html = os.path.join(os.path.dirname(__file__), "static", "admin.html")


@app.get("/admin/")
async def admin_dashboard():
    """Serve the admin monitoring dashboard."""
    return FileResponse(_admin_html, media_type="text/html")


# Mount static files for the chat widget.
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
