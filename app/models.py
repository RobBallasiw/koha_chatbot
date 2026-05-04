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
    timestamp: float | None = None  # Unix timestamp of the response
    client_search: str | None = None  # If set, client should search Koha with this query
    image_url: str | None = None  # Optional image URL to display with the reply


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
    opac_url: str | None = None  # Link to the record in the Koha OPAC


class ItemAvailability(BaseModel):
    """Availability information for a single copy of an item."""

    branch: str
    status: str  # "available" | "checked_out" | "on_hold" | etc.
    call_number: str | None = None
    due_date: str | None = None  # ISO date string if checked out


class FaqItem(BaseModel):
    """A single FAQ entry shown as a quick-reply button in the chat widget."""

    label: str  # Button label shown in the widget
    question: str  # The question text sent when the button is clicked
    content: str = ""  # The answer content the bot returns
    image_url: str = ""  # Optional image URL shown with the reply


class LibraryInfo(BaseModel):
    """Structured library information stored as FAQ entries.

    Each FAQ has a label (button text), question (sent on click),
    and content (the bot's reply). Legacy fields are kept for
    backward compatibility when loading old JSON files.
    """

    faqs: list[FaqItem] = []

    # Legacy fields — kept so old library_info.json files still load
    locations: dict = {}
    policies: dict[str, str] = {}
    fines: dict[str, str] = {}
    hours: dict[str, str] = {}

    def get_all_locations(self) -> dict:
        """Return legacy locations dict (for backward compat)."""
        return self.locations


class SessionData:
    """Mutable session state for a single conversation.

    Not a Pydantic model because it holds mutable state (messages list)
    that changes over the lifetime of a session.
    """

    def __init__(self) -> None:
        self.messages: list[dict] = []  # List of {role, content} message dicts
        self.last_accessed: float = time.time()  # Timestamp of last activity
        self.created_at: float = time.time()  # Timestamp of session creation


# --- Admin Chat Monitoring Models ---


class MessageRecord(BaseModel):
    """A single persisted message."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: float  # Unix timestamp


class SessionSummary(BaseModel):
    """Summary of a chat session for the list view."""

    session_id: str
    created_at: float
    last_activity: float
    message_count: int
    status: str  # "active" or "expired"
    display_name: str = ""


class SessionDetail(BaseModel):
    """Full chat session with message history."""

    session_id: str
    created_at: float
    last_activity: float
    message_count: int
    status: str
    display_name: str = ""
    messages: list[MessageRecord]


class SessionListResponse(BaseModel):
    """Paginated list of session summaries."""

    sessions: list[SessionSummary]
    total: int
    page: int
    page_size: int


class SessionStatsResponse(BaseModel):
    """Aggregate session statistics."""

    total_sessions: int
    total_messages: int
    active_sessions: int
    expired_sessions: int


# --- Analytics Models ---


class IntentCount(BaseModel):
    """Count of messages for a single intent."""

    intent: str
    count: int


class HourlyActivity(BaseModel):
    """Message count for a single hour of the day."""

    hour: int  # 0-23
    count: int


class DailyActivity(BaseModel):
    """Message count for a single day of the week."""

    day: str  # "Monday", "Tuesday", etc.
    count: int


class AnalyticsResponse(BaseModel):
    """Full analytics payload for the admin dashboard."""

    intent_breakdown: list[IntentCount]
    hourly_activity: list[HourlyActivity]
    daily_activity: list[DailyActivity]
    avg_messages_per_session: float
    failed_queries: int  # unclear + catalog_vague intents
    total_user_messages: int


# --- Conversation Quality Models ---


class FeedbackRequest(BaseModel):
    """Patron feedback on a bot response."""

    session_id: str
    message_timestamp: float  # timestamp of the assistant message being rated
    rating: int  # 1 = thumbs up, -1 = thumbs down


class FeedbackResponse(BaseModel):
    """Acknowledgement of feedback submission."""

    status: str


class UnansweredQuery(BaseModel):
    """A user message the bot couldn't handle well."""

    session_id: str
    content: str
    intent: str
    timestamp: float
    resolved: bool


class UnansweredQueueResponse(BaseModel):
    """Paginated list of unanswered queries."""

    queries: list[UnansweredQuery]
    total: int
    page: int
    page_size: int


class FeedbackStats(BaseModel):
    """Aggregate feedback statistics."""

    total_ratings: int
    positive: int
    negative: int
    satisfaction_rate: float  # percentage of positive ratings


class FeedbackEntry(BaseModel):
    """A single feedback entry for the admin view."""

    session_id: str
    user_message: str
    assistant_message: str
    rating: int
    timestamp: float


# --- Session Management Models ---


class SessionFlag(BaseModel):
    """A flag/note on a session for admin follow-up."""

    session_id: str
    note: str
    created_at: float


class BulkCleanupResponse(BaseModel):
    """Result of a bulk session cleanup operation."""

    deleted_sessions: int
    deleted_messages: int
