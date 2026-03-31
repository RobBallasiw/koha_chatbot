"""Main FastAPI application — chat endpoint and request routing."""

import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.catalog_handler import handle_catalog_query
from app.config import Settings, load_settings
from app.groq_client import GroqClient
from app.library_info_handler import handle_library_info_query, load_library_info
from app.models import ChatRequest, ChatResponse, ErrorResponse, LibraryInfo
from app.query_classifier import classify_query
from app.session_manager import SessionManager

app = FastAPI(title="Library AI Chatbot")

# CORS middleware for iframe embedding from any Koha instance.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Module-level variables initialised during the startup event.
settings: Settings | None = None
groq_client: GroqClient | None = None
session_manager: SessionManager | None = None
library_info: LibraryInfo | None = None

CLARIFYING_MESSAGE = (
    "I'm not sure I understand your question. Could you please clarify? "
    "I can help you search the library catalog or answer questions about "
    "library hours, policies, and fines."
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
    global settings, groq_client, session_manager, library_info

    settings = load_settings()
    groq_client = GroqClient(api_key=settings.groq_api_key)
    session_manager = SessionManager()
    library_info = load_library_info(settings.library_info_path)

    # Background task that purges expired sessions every 5 minutes.
    asyncio.create_task(_periodic_cleanup(session_manager))


@app.get("/health")
async def health():
    """Simple health-check endpoint."""
    return {"status": "ok"}


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

    # --- Classify intent ---
    client = groq_client  # may be None before startup wiring
    classification = classify_query(client, request.message, history)

    # --- Route to handler ---
    reply: str
    if classification.intent == "catalog_search":
        koha_url = settings.koha_api_url if settings else ""
        reply = await handle_catalog_query(
            client, request.message, koha_url, history
        )
    elif classification.intent == "library_info":
        reply = handle_library_info_query(
            client, request.message, library_info, history
        )
    else:
        # "unclear" intent — ask for clarification
        reply = CLARIFYING_MESSAGE

    # --- Store conversation turn ---
    session_mgr.add_message(request.session_id, "user", request.message)
    session_mgr.add_message(request.session_id, "assistant", reply)

    return ChatResponse(reply=reply, session_id=request.session_id)


# Mount static files for the chat widget.
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
