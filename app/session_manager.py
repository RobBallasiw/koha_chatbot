"""Session manager — in-memory conversation history per session."""

import time

from app.models import SessionData

# Maximum number of messages retained per session.
MAX_MESSAGES = 20

# Sessions inactive longer than this (seconds) are considered expired.
SESSION_TIMEOUT = 30 * 60  # 30 minutes


class SessionManager:
    """Manages per-session conversation history in memory."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionData] = {}

    def get_or_create_session(self, session_id: str) -> SessionData:
        """Return the session for *session_id*, creating one if it doesn't exist.

        Also refreshes the ``last_accessed`` timestamp so the session
        stays alive.
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionData()
        session = self._sessions[session_id]
        session.last_accessed = time.time()
        return session

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """Append a message to the session and enforce the history cap.

        Parameters
        ----------
        session_id:
            The session to add the message to (created if missing).
        role:
            ``"user"`` or ``"assistant"``.
        content:
            The message text.
        """
        session = self.get_or_create_session(session_id)
        session.messages.append({"role": role, "content": content})
        # Keep only the most recent MAX_MESSAGES entries.
        if len(session.messages) > MAX_MESSAGES:
            session.messages = session.messages[-MAX_MESSAGES:]

    def get_history(self, session_id: str) -> list[dict]:
        """Return the message list for *session_id* (empty list for new sessions)."""
        session = self.get_or_create_session(session_id)
        return session.messages

    def cleanup_expired(self) -> None:
        """Remove all sessions that have been inactive for longer than SESSION_TIMEOUT."""
        now = time.time()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if now - session.last_accessed > SESSION_TIMEOUT
        ]
        for sid in expired:
            del self._sessions[sid]
