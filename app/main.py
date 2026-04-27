"""Main FastAPI application — chat endpoint and request routing."""

import asyncio
import logging
import os
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
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
    "I'm your library assistant — I can help you with:\n"
    "📚 Finding books in the catalog\n"
    "🕐 Library hours and locations\n"
    "📋 Policies, fines, and membership info\n\n"
    "What would you like to know?"
)

GREETING_MESSAGE = (
    "Hey there! 👋 I'm your library assistant. "
    "I can help you find books, check library hours, or answer questions about policies and fines. "
    "What can I do for you?"
)

HANDOFF_ACTIVATED_MESSAGE = (
    "I've notified a librarian — they'll join this chat shortly! 📨"
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
        logger.warning("Failed to initialise settings store")

    # Try loading library info from database (overrides file if present)
    try:
        from app.staff_routes import staff_store as _ss
        if _ss is not None:
            db_val = _ss.get_setting("library_info_json")
            if db_val:
                import json as _json
                library_info = LibraryInfo(**_json.loads(db_val))
                logger.info("Loaded library info from database")
    except Exception:
        logger.info("No library info in database, using file")

    # Background task that purges expired sessions every 5 minutes.
    asyncio.create_task(_periodic_cleanup(session_manager))


@app.get("/debug/koha-test")
async def debug_koha_test():
    """Debug endpoint — test if we can reach the Koha catalog."""
    import httpx
    koha_url = os.environ.get("KOHA_API_URL", "not set")
    url = f"{koha_url.rstrip('/')}/cgi-bin/koha/opac-search.pl"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
            resp = await http.get(
                url,
                params={"q": "java", "format": "rss"},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            )
            return {
                "koha_api_url": koha_url,
                "search_url": url,
                "status_code": resp.status_code,
                "response_length": len(resp.text),
                "first_200_chars": resp.text[:200],
            }
    except Exception as exc:
        return {
            "koha_api_url": koha_url,
            "search_url": url,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


@app.post("/api/format-results")
async def format_results(request: dict):
    """Format raw catalog search results from client-side Koha search."""
    results = request.get("results", [])
    session_id = request.get("session_id", "")
    message = request.get("message", "")

    if not results:
        from app.catalog_handler import NO_RESULTS_MESSAGE
        reply = NO_RESULTS_MESSAGE
    else:
        lines = []
        for i, rec in enumerate(results[:20], start=1):
            parts = [f"{i}. {rec.get('title', 'Unknown')} by {rec.get('author', 'Unknown Author')}"]
            if rec.get("url"):
                parts.append(f"   View in catalog: {rec['url']}")
            lines.append("\n".join(parts))
        reply = "Here's what I found in the catalog 📚:\n\n" + "\n".join(lines)

    # Store in session
    if session_manager and session_id:
        session_manager.add_message(session_id, "assistant", reply)

    # Persist
    if session_store and session_id:
        try:
            session_store.save_message(session_id, "assistant", reply)
        except Exception:
            pass

    return ChatResponse(reply=reply, session_id=session_id, timestamp=time.time())


@app.get("/health")
async def health():
    """Simple health-check endpoint."""
    has_key = bool(os.environ.get("OPENROUTER_API_KEY"))
    llm_url = os.environ.get("OLLAMA_URL", "not set")
    llm_model = os.environ.get("OLLAMA_MODEL", "not set")
    return {
        "status": "ok",
        "llm_enabled": has_key,
        "llm_url": llm_url,
        "llm_model": llm_model,
    }


@app.get("/api/session-status/{session_id}")
async def session_status(session_id: str):
    """Check if a session is still active or has expired."""
    if session_store is None:
        return {"status": "unknown"}
    try:
        detail = session_store.get_session(session_id)
        if detail is None:
            return {"status": "not_found"}
        return {"status": detail.status}
    except Exception:
        return {"status": "unknown"}


@app.get("/")
async def root():
    """Root endpoint — confirms the API is running."""
    return {"status": "ok", "app": "Library AI Chatbot"}


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
        # Patron is in handoff mode — save their message to the live chat session
        session_mgr.add_message(request.session_id, "user", request.message)
        _store = session_store
        _sid = request.session_id
        _msg = request.message
        async def _persist_handoff():
            try:
                live_chat = _store.get_active_live_chat(_sid)
                if live_chat:
                    _store.save_live_chat_message(live_chat["id"], "user", _msg)
                else:
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
                # Create a separate live chat session
                live_chat_id = session_store.create_live_chat(request.session_id)
                logger.info("Created live chat %s for session %s", live_chat_id, request.session_id)
            except Exception:
                logger.exception("Failed to activate handoff for session %s", request.session_id)
        # Send notification in background (ntfy push or email)
        if settings:
            _cfg = settings
            _sid = request.session_id
            async def _send_notification():
                import json as _json
                from app.email_notify import send_ntfy_notification, send_handoff_email, send_staff_notify_email
                if _cfg.ntfy_topic:
                    send_ntfy_notification(_cfg.ntfy_topic, _sid, _cfg.chatbot_public_url)
                from app.email_notify import _use_service_account
                _has_email = (_cfg.smtp_email and _cfg.smtp_password) or _use_service_account()
                if _has_email:
                    # 1. Email all active staff contacts (personalized by name)
                    try:
                        from app.staff_routes import staff_store as _ss
                        if _ss:
                            contacts = _ss.get_active_contacts()
                            for c in contacts:
                                try:
                                    send_staff_notify_email(
                                        _cfg.smtp_email, _cfg.smtp_password,
                                        c["email"], c["name"], _sid, _cfg.chatbot_public_url,
                                    )
                                except Exception:
                                    logger.exception("Failed to notify contact %s", c["email"])
                    except Exception:
                        pass
                    # 2. Also email notification-emails list (legacy/fallback)
                    emails = []
                    try:
                        from app.staff_routes import staff_store as _ss
                        if _ss:
                            raw = _ss.get_setting("notification_emails")
                            if raw:
                                emails = _json.loads(raw)
                    except Exception:
                        pass
                    if not emails and _cfg.librarian_email:
                        emails = [_cfg.librarian_email]
                    for email in emails:
                        try:
                            send_handoff_email(
                                _cfg.smtp_email, _cfg.smtp_password, email.strip(),
                                _sid, _cfg.chatbot_public_url,
                            )
                        except Exception:
                            logger.exception("Failed to send notification to %s", email)
            asyncio.create_task(_send_notification())
        session_mgr.add_message(request.session_id, "user", request.message)
        session_mgr.add_message(request.session_id, "assistant", reply)
        return ChatResponse(reply=reply, session_id=request.session_id, timestamp=time.time())
    elif classification.intent == "catalog_search":
        koha_url = settings.koha_api_url if settings else ""
        # First try server-side search
        reply = await handle_catalog_query(
            client, request.message, koha_url, history
        )
        # If server-side search failed (likely 403 from WAF), fall back to client-side
        if reply == CLARIFYING_MESSAGE or "couldn't find" in reply:
            from app.catalog_handler import _extract_keywords, _is_vague_query
            raw_kw = _extract_keywords(request.message)
            if not _is_vague_query(raw_kw):
                # Always use raw keywords — most reliable for client-side search
                session_mgr.add_message(request.session_id, "user", request.message)
                return ChatResponse(
                    reply="",
                    session_id=request.session_id,
                    timestamp=time.time(),
                    client_search=raw_kw,
                )
    elif classification.intent == "library_info":
        reply = handle_library_info_query(
            client, request.message, library_info, history
        )
    elif classification.intent == "greeting":
        # Use LLM for a friendly greeting if available
        if client and os.environ.get("OPENROUTER_API_KEY"):
            try:
                messages_for_llm: list[dict] = []
                if history:
                    messages_for_llm.extend(history[-4:])
                messages_for_llm.append({"role": "user", "content": request.message})
                llm_reply = client.chat(messages_for_llm)
                if isinstance(llm_reply, str) and llm_reply and "trouble" not in llm_reply.lower():
                    reply = llm_reply
                else:
                    reply = GREETING_MESSAGE
            except Exception:
                reply = GREETING_MESSAGE
        else:
            reply = GREETING_MESSAGE
    else:
        # "unclear" intent — use LLM if available, otherwise static message
        if client and os.environ.get("OPENROUTER_API_KEY"):
            try:
                messages_for_llm = []
                if history:
                    messages_for_llm.extend(history[-4:])
                messages_for_llm.append({"role": "user", "content": request.message})
                llm_reply = client.chat(messages_for_llm)
                if isinstance(llm_reply, str) and llm_reply and "trouble" not in llm_reply.lower():
                    reply = llm_reply
                else:
                    reply = CLARIFYING_MESSAGE
            except Exception:
                reply = CLARIFYING_MESSAGE
        else:
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
            # End any active live chat
            live_chat = session_store.get_active_live_chat(request.session_id)
            if live_chat:
                session_store.end_live_chat(live_chat["id"])
            # Deactivate any active handoff
            if session_store.is_handoff_active(request.session_id):
                session_store.deactivate_handoff(request.session_id)
            session_store.close_session(request.session_id)
        except Exception:
            logger.exception("Failed to close session %s", request.session_id)
    return {"status": "ok"}


@app.post("/api/cancel-handoff")
async def cancel_handoff(request: ChatRequest):
    """Allow a patron to cancel their librarian handoff request."""
    if not request.session_id or not request.session_id.strip():
        return JSONResponse(status_code=400, content={"error": "Session identifier is required"})
    if session_store is None:
        return JSONResponse(status_code=500, content={"error": "Store not available"})
    try:
        live_chat = session_store.get_active_live_chat(request.session_id)
        if not live_chat:
            return JSONResponse(status_code=404, content={"error": "No active handoff"})
        if live_chat["staff_username"]:
            return JSONResponse(status_code=409, content={"error": "A librarian has already joined. Cannot cancel."})
        session_store.cancel_live_chat(live_chat["id"])
        session_store.save_message(
            request.session_id, "assistant",
            "Librarian request cancelled. Back to help! 👋 What else can I do for you?"
        )
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to cancel handoff for session %s", request.session_id)
        return JSONResponse(status_code=500, content={"error": "Failed to cancel handoff"})


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
    # Look up who handled this session — check live chat first, fall back to old claim
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
        return {"messages": [], "handoff_active": False, "handled_by": None, "live_chat_id": None}
    try:
        handoff = session_store.is_handoff_active(session_id)
        live_chat = session_store.get_active_live_chat(session_id) if handoff else None
        live_chat_id = live_chat["id"] if live_chat else None
        handled_by = live_chat["staff_username"] if live_chat else None

        # Get messages from the live chat session if it exists
        if live_chat_id:
            msgs = session_store.get_live_chat_messages(live_chat_id, since)
        else:
            msgs = session_store.get_new_messages_since(session_id, since)

        return {
            "messages": msgs,
            "handoff_active": handoff,
            "handled_by": handled_by,
            "live_chat_id": live_chat_id,
        }
    except Exception:
        logger.exception("Failed to poll messages for session %s", session_id)
        return {"messages": [], "handoff_active": False, "handled_by": None, "live_chat_id": None}


# Serve admin dashboard HTML at /admin/.
_admin_html = os.path.join(os.path.dirname(__file__), "static", "admin.html")
_live_chat_html = os.path.join(os.path.dirname(__file__), "static", "live-chat.html")


@app.get("/admin/")
async def admin_dashboard():
    """Serve the admin monitoring dashboard with no-cache headers."""
    return HTMLResponse(
        content=open(_admin_html, "r", encoding="utf-8").read(),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/chat/")
async def live_chat_page():
    """Serve the standalone live chat page with API key injected."""
    api_key = os.environ.get("ADMIN_API_KEY", "")
    with open(_live_chat_html, "r", encoding="utf-8") as f:
        html = f.read()
    # Inject the API key so the page can auto-connect
    html = html.replace("__INJECTED_API_KEY__", api_key)
    return HTMLResponse(html)


@app.get("/admin/chat/")
async def live_chat_page_alt():
    """Serve the live chat page at /admin/chat/ too."""
    return await live_chat_page()


# Mount static files for the chat widget.
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
