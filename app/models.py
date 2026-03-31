"""Data models for the Library AI Chatbot."""

import time

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Incoming chat request from the patron."""

    message: str  # Non-empty patron message
    session_id: str  # Unique session identifier


class ChatResponse(BaseModel):
    """Outgoing chat response to the patron."""

    reply: str  # Chatbot response text
    session_id: str  # Session identifier


class ErrorResponse(BaseModel):
    """Error response returned for invalid requests."""

    error: str  # Descriptive error message


class ClassificationResult(BaseModel):
    """Result of query intent classification."""

    intent: str  # "catalog_search" | "library_info" | "unclear"
    confidence: float  # 0.0 to 1.0


class SearchParameters(BaseModel):
    """Structured search parameters extracted from natural language."""

    title: str | None = None
    author: str | None = None
    subject: str | None = None
    isbn: str | None = None


class CatalogRecord(BaseModel):
    """A bibliographic record from the Koha catalog."""

    title: str
    author: str
    call_number: str | None = None
    isbn: str | None = None


class ItemAvailability(BaseModel):
    """Availability information for a single copy of an item."""

    branch: str
    status: str  # "available" | "checked_out" | "on_hold" | etc.
    call_number: str | None = None
    due_date: str | None = None  # ISO date string if checked out


class LibraryInfo(BaseModel):
    """Structured library information loaded from the info store."""

    hours: dict[str, str]
    policies: dict[str, str]
    fines: dict[str, str]


class SessionData:
    """Mutable session state for a single conversation.

    Not a Pydantic model because it holds mutable state (messages list)
    that changes over the lifetime of a session.
    """

    def __init__(self) -> None:
        self.messages: list[dict] = []  # List of {role, content} message dicts
        self.last_accessed: float = time.time()  # Timestamp of last activity
        self.created_at: float = time.time()  # Timestamp of session creation
