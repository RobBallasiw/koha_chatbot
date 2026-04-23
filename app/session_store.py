"""Turso/SQLite-backed persistent storage for chat sessions and messages."""

import logging
import random
import time
from pathlib import Path

from app.db import get_connection, sync_if_needed, libsql

from app.models import (
    AnalyticsResponse,
    BulkCleanupResponse,
    DailyActivity,
    FeedbackEntry,
    FeedbackStats,
    HourlyActivity,
    IntentCount,
    MessageRecord,
    SessionDetail,
    SessionFlag,
    SessionListResponse,
    SessionStatsResponse,
    SessionSummary,
    UnansweredQuery,
    UnansweredQueueResponse,
)
from app.session_manager import SESSION_TIMEOUT

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "/tmp/sessions.db"

_ADJECTIVES = [
    "Blue", "Red", "Green", "Gold", "Silver", "Bright", "Calm", "Swift",
    "Warm", "Cool", "Happy", "Brave", "Quiet", "Bold", "Gentle", "Wise",
    "Lucky", "Sunny", "Misty", "Coral", "Amber", "Ivory", "Jade", "Ruby",
]
_NOUNS = [
    "Owl", "Fox", "Bear", "Deer", "Wolf", "Hawk", "Dove", "Lynx",
    "Panda", "Otter", "Robin", "Crane", "Finch", "Heron", "Koala", "Raven",
    "Tiger", "Eagle", "Whale", "Seal", "Lark", "Swan", "Wren", "Jay",
]


def _generate_display_name() -> str:
    """Generate a random friendly name like 'Blue Owl 42'."""
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    num = random.randint(10, 99)
    return f"{adj} {noun} {num}"


class SessionStore:
    """Persistent session store backed by SQLite.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Defaults to ``data/sessions.db``
        but can be overridden via the ``SESSION_DB_PATH`` env var.
    """

    def __init__(self, db_path: str | None = None) -> None:
        import os

        self.db_path = db_path or os.environ.get("SESSION_DB_PATH", _DEFAULT_DB_PATH)
        self._init_db()

    # ------------------------------------------------------------------
    # Database initialisation
    # ------------------------------------------------------------------

    def _get_connection(self):
        """Return a new connection with row-factory enabled."""
        conn = get_connection(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass  # Turso may not support all PRAGMAs
        return conn

    def _commit(self, conn) -> None:
        """Commit and sync with Turso if applicable."""
        conn.commit()
        sync_if_needed(conn)

    def _init_db(self) -> None:
        """Create tables and indexes if they don't already exist."""
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass  # Turso URLs don't need local directories
        conn = self._get_connection()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    last_activity REAL NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    handoff_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    intent TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_last_activity
                    ON sessions(last_activity);

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    message_timestamp REAL NOT NULL,
                    rating INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_feedback_session
                    ON feedback(session_id);

                CREATE TABLE IF NOT EXISTS session_flags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    note TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );

                CREATE TABLE IF NOT EXISTS staff_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    handoff_num INTEGER NOT NULL DEFAULT 1,
                    staff_username TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(session_id, handoff_num)
                );

                CREATE INDEX IF NOT EXISTS idx_staff_ratings_staff
                    ON staff_ratings(staff_username);
                """
            )
            conn.commit()
        finally:
            conn.close()

        self._migrate_db()

    def _migrate_db(self) -> None:
        """Add columns introduced after the initial schema."""
        conn = self._get_connection()
        try:
            # Check if 'intent' column exists on messages table.
            cols = [
                row["name"]
                for row in conn.execute("PRAGMA table_info(messages)").fetchall()
            ]
            if "intent" not in cols:
                conn.execute("ALTER TABLE messages ADD COLUMN intent TEXT")
                conn.commit()
            # Ensure the intent index exists.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_intent ON messages(intent)"
            )
            # Composite index for analytics queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_analytics ON messages(role, timestamp)"
            )
            conn.commit()

            # Ensure feedback table exists (for databases created before this feature).
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    message_timestamp REAL NOT NULL,
                    rating INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_session
                    ON feedback(session_id);

                CREATE TABLE IF NOT EXISTS session_flags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    note TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );
                """
            )
            conn.commit()

            # Add handoff_active column for "Talk to a Librarian" feature.
            sess_cols = [
                row["name"]
                for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
            ]
            if "handoff_active" not in sess_cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN handoff_active INTEGER NOT NULL DEFAULT 0")
                conn.commit()

            # Add handoff_claimed_by column to track which staff is handling the session.
            if "handoff_claimed_by" not in sess_cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN handoff_claimed_by TEXT DEFAULT NULL")
                conn.commit()

            # Ensure staff_ratings table exists with correct schema.
            # If the old schema (UNIQUE on session_id only) exists, migrate it.
            # Ensure staff_ratings table has correct schema.
            sr_cols = [row["name"] for row in conn.execute("PRAGMA table_info(staff_ratings)").fetchall()]
            if sr_cols:
                # Check if the table has the old UNIQUE(session_id) constraint
                # by inspecting the CREATE TABLE SQL
                schema_row = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='staff_ratings'"
                ).fetchone()
                schema_sql = schema_row[0] if schema_row else ""
                needs_rebuild = (
                    "handoff_num" not in sr_cols
                    or ("session_id TEXT NOT NULL UNIQUE" in schema_sql and "UNIQUE(session_id, handoff_num)" not in schema_sql)
                )
                if needs_rebuild:
                    conn.execute("PRAGMA foreign_keys=OFF")
                    conn.executescript("""
                        CREATE TABLE IF NOT EXISTS staff_ratings_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            session_id TEXT NOT NULL,
                            handoff_num INTEGER NOT NULL DEFAULT 1,
                            staff_username TEXT NOT NULL,
                            rating INTEGER NOT NULL,
                            created_at REAL NOT NULL,
                            UNIQUE(session_id, handoff_num)
                        );
                        INSERT OR IGNORE INTO staff_ratings_new (session_id, handoff_num, staff_username, rating, created_at)
                            SELECT session_id, COALESCE(handoff_num, 1), staff_username, rating, created_at FROM staff_ratings;
                        DROP TABLE staff_ratings;
                        ALTER TABLE staff_ratings_new RENAME TO staff_ratings;
                        CREATE INDEX IF NOT EXISTS idx_staff_ratings_staff ON staff_ratings(staff_username);
                    """)
                    conn.execute("PRAGMA foreign_keys=ON")
                    conn.commit()
            else:
                # Table doesn't exist at all — create fresh
                conn.executescript("""
                    CREATE TABLE staff_ratings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        handoff_num INTEGER NOT NULL DEFAULT 1,
                        staff_username TEXT NOT NULL,
                        rating INTEGER NOT NULL,
                        created_at REAL NOT NULL,
                        UNIQUE(session_id, handoff_num)
                    );
                    CREATE INDEX IF NOT EXISTS idx_staff_ratings_staff ON staff_ratings(staff_username);
                """)
                conn.commit()

            # Add handoff_count to sessions if missing
            if "handoff_count" not in sess_cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN handoff_count INTEGER NOT NULL DEFAULT 0")
                conn.commit()

            # Add display_name column for friendly session names
            if "display_name" not in sess_cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN display_name TEXT DEFAULT ''")
                conn.commit()

            # Create live_chat_sessions table for separate live chat tracking
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS live_chat_sessions (
                    id TEXT PRIMARY KEY,
                    parent_session_id TEXT NOT NULL,
                    staff_username TEXT,
                    status TEXT NOT NULL DEFAULT 'waiting',
                    created_at REAL NOT NULL,
                    claimed_at REAL,
                    ended_at REAL,
                    FOREIGN KEY (parent_session_id) REFERENCES sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_lcs_parent ON live_chat_sessions(parent_session_id);
                CREATE INDEX IF NOT EXISTS idx_lcs_status ON live_chat_sessions(status);

                CREATE TABLE IF NOT EXISTS live_chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    live_chat_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (live_chat_id) REFERENCES live_chat_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_lcm_chat ON live_chat_messages(live_chat_id);
            """)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_message(
        self, session_id: str, role: str, content: str, timestamp: float | None = None,
        intent: str | None = None,
    ) -> None:
        """Persist a single message, creating the session row if needed.

        Parameters
        ----------
        session_id:
            Unique session identifier.
        role:
            ``"user"`` or ``"assistant"``.
        content:
            The message text.
        timestamp:
            Unix timestamp for the message.  Defaults to ``time.time()``.
        intent:
            The classified intent for this message (typically set on user messages).
        """
        ts = timestamp if timestamp is not None else time.time()
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            # Upsert session row — generate display_name for new sessions
            name = _generate_display_name()
            cur.execute(
                """
                INSERT INTO sessions (session_id, created_at, last_activity, message_count, display_name)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_activity = MAX(sessions.last_activity, excluded.last_activity),
                    message_count = sessions.message_count + 1
                """,
                (session_id, ts, ts, name),
            )
            cur.execute(
                """
                INSERT INTO messages (session_id, role, content, timestamp, intent)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, ts, intent),
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to save message for session %s", session_id)
            raise
        finally:
            conn.close()

    def close_session(self, session_id: str) -> None:
        """Mark a session as expired by setting last_activity far in the past."""
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE sessions SET last_activity = 0 WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to close session %s", session_id)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Handoff (Talk to a Librarian) operations
    # ------------------------------------------------------------------

    def activate_handoff(self, session_id: str) -> None:
        """Mark a session as needing librarian attention and increment handoff count."""
        conn = self._get_connection()
        try:
            conn.execute(
                """UPDATE sessions
                   SET handoff_active = 1,
                       handoff_claimed_by = NULL,
                       handoff_count = COALESCE(handoff_count, 0) + 1
                   WHERE session_id = ?""",
                (session_id,),
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to activate handoff for session %s", session_id)
            raise
        finally:
            conn.close()

    def deactivate_handoff(self, session_id: str) -> None:
        """Mark a handoff session as resolved. Keeps claimed_by as a record of who handled it."""
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE sessions SET handoff_active = 0 WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to deactivate handoff for session %s", session_id)
            raise
        finally:
            conn.close()

    def claim_handoff(self, session_id: str, username: str) -> dict:
        """Claim a handoff session for a staff member.

        Returns a dict with ``"ok": True`` on success, or
        ``"ok": False, "claimed_by": "<username>"`` if already claimed
        by someone else.
        """
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT handoff_claimed_by FROM sessions WHERE session_id = ? AND handoff_active = 1",
                (session_id,),
            ).fetchone()
            if row is None:
                return {"ok": False, "error": "Session not found or handoff not active"}
            current = row["handoff_claimed_by"]
            if current and current != username:
                return {"ok": False, "claimed_by": current}
            conn.execute(
                "UPDATE sessions SET handoff_claimed_by = ? WHERE session_id = ?",
                (username, session_id),
            )
            conn.commit()
            return {"ok": True}
        except Exception:
            logger.exception("Failed to claim handoff for session %s", session_id)
            raise
        finally:
            conn.close()

    def release_handoff(self, session_id: str) -> None:
        """Release a claimed handoff session so another staff can pick it up."""
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE sessions SET handoff_claimed_by = NULL WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to release handoff for session %s", session_id)
            raise
        finally:
            conn.close()

    def get_handoff_claim(self, session_id: str) -> str | None:
        """Return the username of whoever claimed this session, or None."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT handoff_claimed_by FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row["handoff_claimed_by"] if row else None
        finally:
            conn.close()

    def get_handoff_count(self, session_id: str) -> int:
        """Return the current handoff number for a session."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT COALESCE(handoff_count, 1) AS cnt FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row["cnt"] if row else 1
        finally:
            conn.close()

    def is_handoff_active(self, session_id: str) -> bool:
        """Check if a session has an active librarian handoff.

        Returns False if the session has no active handoff or live chat.
        """
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT handoff_active FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not row or not row["handoff_active"]:
                return False
            # Check if there's an active live chat — if so, handoff is active regardless of parent expiry
            lc = conn.execute(
                "SELECT id FROM live_chat_sessions WHERE parent_session_id = ? AND status IN ('waiting', 'active') LIMIT 1",
                (session_id,),
            ).fetchone()
            if lc:
                return True
            # No live chat — check parent session expiry
            ts_row = conn.execute(
                "SELECT last_activity FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if ts_row and self._session_status(ts_row["last_activity"]) == "expired":
                return False
            return True
        finally:
            conn.close()

    def get_handoff_sessions(self, page: int = 1, page_size: int = 20) -> dict:
        """Return sessions with active handoff requests.

        Automatically deactivates handoffs for expired sessions.
        """
        page = max(1, page)
        page_size = max(1, page_size)
        conn = self._get_connection()
        try:
            # Auto-deactivate handoffs for expired sessions
            cutoff = time.time() - SESSION_TIMEOUT
            conn.execute(
                "UPDATE sessions SET handoff_active = 0 WHERE handoff_active = 1 AND last_activity < ?",
                (cutoff,),
            )
            conn.commit()

            total = conn.execute(
                "SELECT COUNT(*) AS cnt FROM sessions WHERE handoff_active = 1"
            ).fetchone()["cnt"]
            rows = conn.execute(
                """
                SELECT session_id, created_at, last_activity, message_count, handoff_claimed_by
                FROM sessions WHERE handoff_active = 1
                ORDER BY last_activity DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, (page - 1) * page_size),
            ).fetchall()
            sessions = [
                {
                    "session_id": r["session_id"],
                    "created_at": r["created_at"],
                    "last_activity": r["last_activity"],
                    "message_count": r["message_count"],
                    "status": self._session_status(r["last_activity"]),
                    "claimed_by": r["handoff_claimed_by"],
                }
                for r in rows
            ]
            return {"sessions": sessions, "total": total, "page": page, "page_size": page_size}
        finally:
            conn.close()

    def get_new_messages_since(self, session_id: str, since_ts: float) -> list[dict]:
        """Return messages in a session newer than the given timestamp."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT role, content, timestamp FROM messages
                WHERE session_id = ? AND timestamp > ?
                ORDER BY timestamp ASC, id ASC
                """,
                (session_id, since_ts),
            ).fetchall()
            return [
                {"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]}
                for r in rows
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Live chat session operations
    # ------------------------------------------------------------------

    def create_live_chat(self, parent_session_id: str) -> str:
        """Create a new live chat session linked to a parent bot session.

        Returns the new live chat session ID.
        """
        import uuid
        live_chat_id = str(uuid.uuid4())
        now = time.time()
        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT INTO live_chat_sessions (id, parent_session_id, status, created_at)
                   VALUES (?, ?, 'waiting', ?)""",
                (live_chat_id, parent_session_id, now),
            )
            conn.commit()
            return live_chat_id
        except Exception:
            logger.exception("Failed to create live chat for session %s", parent_session_id)
            raise
        finally:
            conn.close()

    def get_active_live_chat(self, parent_session_id: str) -> dict | None:
        """Return the active live chat session for a parent session, or None."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                """SELECT id, parent_session_id, staff_username, status, created_at, claimed_at, ended_at
                   FROM live_chat_sessions
                   WHERE parent_session_id = ? AND status IN ('waiting', 'active')
                   ORDER BY created_at DESC LIMIT 1""",
                (parent_session_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "parent_session_id": row["parent_session_id"],
                "staff_username": row["staff_username"],
                "status": row["status"],
                "created_at": row["created_at"],
                "claimed_at": row["claimed_at"],
                "ended_at": row["ended_at"],
            }
        finally:
            conn.close()

    def claim_live_chat(self, live_chat_id: str, username: str) -> dict:
        """Claim a live chat session. Returns ok/error dict."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT staff_username, status FROM live_chat_sessions WHERE id = ?",
                (live_chat_id,),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Live chat not found"}
            if row["status"] == "ended":
                return {"ok": False, "error": "Live chat already ended"}
            if row["staff_username"] and row["staff_username"] != username:
                return {"ok": False, "claimed_by": row["staff_username"]}
            conn.execute(
                """UPDATE live_chat_sessions
                   SET staff_username = ?, status = 'active', claimed_at = ?
                   WHERE id = ?""",
                (username, time.time(), live_chat_id),
            )
            # Also update the parent session's handoff_claimed_by for backward compat
            parent = conn.execute(
                "SELECT parent_session_id FROM live_chat_sessions WHERE id = ?",
                (live_chat_id,),
            ).fetchone()
            if parent:
                conn.execute(
                    "UPDATE sessions SET handoff_claimed_by = ? WHERE session_id = ?",
                    (username, parent["parent_session_id"]),
                )
            conn.commit()
            return {"ok": True}
        except Exception:
            logger.exception("Failed to claim live chat %s", live_chat_id)
            raise
        finally:
            conn.close()

    def release_live_chat(self, live_chat_id: str) -> None:
        """Release a claimed live chat so another staff can pick it up."""
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE live_chat_sessions SET staff_username = NULL, status = 'waiting', claimed_at = NULL WHERE id = ?",
                (live_chat_id,),
            )
            parent = conn.execute(
                "SELECT parent_session_id FROM live_chat_sessions WHERE id = ?",
                (live_chat_id,),
            ).fetchone()
            if parent:
                conn.execute(
                    "UPDATE sessions SET handoff_claimed_by = NULL WHERE session_id = ?",
                    (parent["parent_session_id"],),
                )
            conn.commit()
        except Exception:
            logger.exception("Failed to release live chat %s", live_chat_id)
            raise
        finally:
            conn.close()

    def end_live_chat(self, live_chat_id: str) -> None:
        """End a live chat session."""
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE live_chat_sessions SET status = 'ended', ended_at = ? WHERE id = ?",
                (time.time(), live_chat_id),
            )
            # Deactivate handoff on parent session
            parent = conn.execute(
                "SELECT parent_session_id FROM live_chat_sessions WHERE id = ?",
                (live_chat_id,),
            ).fetchone()
            if parent:
                conn.execute(
                    "UPDATE sessions SET handoff_active = 0 WHERE session_id = ?",
                    (parent["parent_session_id"],),
                )
            conn.commit()
        except Exception:
            logger.exception("Failed to end live chat %s", live_chat_id)
            raise
        finally:
            conn.close()

    def cancel_live_chat(self, live_chat_id: str) -> bool:
        """Cancel a live chat (only if not yet claimed). Returns True if cancelled."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT staff_username, status FROM live_chat_sessions WHERE id = ?",
                (live_chat_id,),
            ).fetchone()
            if not row or row["status"] == "ended":
                return False
            if row["staff_username"]:
                return False  # Already claimed
            conn.execute(
                "UPDATE live_chat_sessions SET status = 'ended', ended_at = ? WHERE id = ?",
                (time.time(), live_chat_id),
            )
            parent = conn.execute(
                "SELECT parent_session_id FROM live_chat_sessions WHERE id = ?",
                (live_chat_id,),
            ).fetchone()
            if parent:
                conn.execute(
                    "UPDATE sessions SET handoff_active = 0 WHERE session_id = ?",
                    (parent["parent_session_id"],),
                )
            conn.commit()
            return True
        except Exception:
            logger.exception("Failed to cancel live chat %s", live_chat_id)
            raise
        finally:
            conn.close()

    def save_live_chat_message(self, live_chat_id: str, role: str, content: str) -> None:
        """Save a message to a live chat session."""
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO live_chat_messages (live_chat_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (live_chat_id, role, content, time.time()),
            )
            # Also update parent session's last_activity to keep it alive
            parent = conn.execute(
                "SELECT parent_session_id FROM live_chat_sessions WHERE id = ?",
                (live_chat_id,),
            ).fetchone()
            if parent:
                conn.execute(
                    "UPDATE sessions SET last_activity = ? WHERE session_id = ?",
                    (time.time(), parent["parent_session_id"]),
                )
            conn.commit()
        except Exception:
            logger.exception("Failed to save live chat message for %s", live_chat_id)
            raise
        finally:
            conn.close()

    def get_live_chat_messages(self, live_chat_id: str, since: float = 0) -> list[dict]:
        """Return messages for a live chat session, optionally since a timestamp."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """SELECT role, content, timestamp FROM live_chat_messages
                   WHERE live_chat_id = ? AND timestamp > ?
                   ORDER BY timestamp ASC, id ASC""",
                (live_chat_id, since),
            ).fetchall()
            return [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in rows]
        finally:
            conn.close()

    def get_all_live_chat_messages(self, live_chat_id: str) -> list[dict]:
        """Return all messages for a live chat session."""
        return self.get_live_chat_messages(live_chat_id, since=0)

    def get_waiting_live_chats(self, page: int = 1, page_size: int = 50) -> dict:
        """Return live chat sessions waiting for or active with a librarian."""
        page = max(1, page)
        page_size = max(1, page_size)
        cutoff = time.time() - SESSION_TIMEOUT
        conn = self._get_connection()
        try:
            # Auto-end live chats that are still waiting and whose parent session expired
            # Don't auto-end active chats (staff is handling them)
            conn.execute(
                """UPDATE live_chat_sessions SET status = 'ended', ended_at = ?
                   WHERE status = 'waiting'
                   AND parent_session_id IN (
                       SELECT session_id FROM sessions WHERE last_activity < ?
                   )""",
                (time.time(), cutoff),
            )
            conn.commit()

            total = conn.execute(
                "SELECT COUNT(*) AS cnt FROM live_chat_sessions WHERE status IN ('waiting', 'active')"
            ).fetchone()["cnt"]
            rows = conn.execute(
                """SELECT lc.id, lc.parent_session_id, lc.staff_username, lc.status,
                          lc.created_at, lc.claimed_at,
                          s.message_count, s.last_activity, s.display_name
                   FROM live_chat_sessions lc
                   JOIN sessions s ON s.session_id = lc.parent_session_id
                   WHERE lc.status IN ('waiting', 'active')
                   ORDER BY lc.created_at DESC
                   LIMIT ? OFFSET ?""",
                (page_size, (page - 1) * page_size),
            ).fetchall()
            sessions = [
                {
                    "live_chat_id": r["id"],
                    "session_id": r["parent_session_id"],
                    "staff_username": r["staff_username"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "claimed_at": r["claimed_at"],
                    "message_count": r["message_count"],
                    "last_activity": r["last_activity"],
                    "display_name": r["display_name"] or "",
                }
                for r in rows
            ]
            return {"sessions": sessions, "total": total, "page": page, "page_size": page_size}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Handoff archive (completed live chat sessions)
    # ------------------------------------------------------------------

    def get_handoff_archive(
        self, page: int = 1, page_size: int = 20, staff: str | None = None, days: int = 30,
    ) -> dict:
        """Return completed handoff interactions — one row per handoff, not per session."""
        page = max(1, page)
        page_size = max(1, page_size)
        cutoff = time.time() - (days * 86400)
        conn = self._get_connection()
        try:
            where = "WHERE sr.created_at >= ?"
            params: list = [cutoff]
            if staff:
                where += " AND sr.staff_username = ?"
                params.append(staff)

            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM staff_ratings sr {where}", params,
            ).fetchone()["cnt"]

            rows = conn.execute(
                f"""
                SELECT sr.id AS rating_id, sr.session_id, sr.handoff_num,
                       sr.staff_username, sr.rating, sr.created_at AS rated_at,
                       s.created_at AS session_created, s.message_count
                FROM staff_ratings sr
                LEFT JOIN sessions s ON s.session_id = sr.session_id
                {where}
                ORDER BY sr.created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [page_size, (page - 1) * page_size],
            ).fetchall()

            entries = [
                {
                    "rating_id": r["rating_id"],
                    "session_id": r["session_id"],
                    "handoff_num": r["handoff_num"],
                    "handled_by": r["staff_username"],
                    "rating": r["rating"],
                    "rated_at": r["rated_at"],
                    "session_created": r["session_created"],
                    "message_count": r["message_count"],
                }
                for r in rows
            ]
            return {"sessions": entries, "total": total, "page": page, "page_size": page_size}
        finally:
            conn.close()

    def get_handoff_messages(self, session_id: str, handoff_num: int = 0) -> list[dict]:
        """Return messages for a specific handoff within a session.

        If *handoff_num* is 0, returns all messages from the first handoff onward.
        Otherwise returns messages from the Nth handoff start up to and including
        the end-handoff bot message, excluding any regular bot chat that follows.
        """
        conn = self._get_connection()
        try:
            # Get all handoff start timestamps (each 'talk_to_librarian' intent)
            starts = conn.execute(
                """
                SELECT timestamp FROM messages
                WHERE session_id = ? AND intent = 'talk_to_librarian'
                ORDER BY timestamp ASC, id ASC
                """,
                (session_id,),
            ).fetchall()

            if not starts:
                return []

            if handoff_num <= 0 or handoff_num > len(starts):
                start_ts = starts[0]["timestamp"]
                end_ts = None
            else:
                start_ts = starts[handoff_num - 1]["timestamp"]
                # Hard boundary: the next handoff start
                next_handoff_ts = starts[handoff_num]["timestamp"] if handoff_num < len(starts) else None

                # Find the last librarian message in this range
                if next_handoff_ts:
                    last_lib = conn.execute(
                        """SELECT MAX(timestamp) AS ts FROM messages
                           WHERE session_id = ? AND role = 'librarian'
                             AND timestamp >= ? AND timestamp < ?""",
                        (session_id, start_ts, next_handoff_ts),
                    ).fetchone()
                else:
                    last_lib = conn.execute(
                        """SELECT MAX(timestamp) AS ts FROM messages
                           WHERE session_id = ? AND role = 'librarian' AND timestamp >= ?""",
                        (session_id, start_ts),
                    ).fetchone()

                if last_lib and last_lib["ts"]:
                    # Include the next assistant message after the last librarian msg (the "Hero is back" message)
                    end_msg = conn.execute(
                        """SELECT timestamp FROM messages
                           WHERE session_id = ? AND role = 'assistant' AND timestamp > ?
                           ORDER BY timestamp ASC, id ASC LIMIT 1""",
                        (session_id, last_lib["ts"]),
                    ).fetchone()
                    # Cut right after that assistant message
                    end_ts = (end_msg["timestamp"] + 0.001) if end_msg else next_handoff_ts
                else:
                    end_ts = next_handoff_ts

            if end_ts is not None:
                rows = conn.execute(
                    """SELECT role, content, timestamp FROM messages
                       WHERE session_id = ? AND timestamp >= ? AND timestamp < ?
                       ORDER BY timestamp ASC, id ASC""",
                    (session_id, start_ts, end_ts),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT role, content, timestamp FROM messages
                       WHERE session_id = ? AND timestamp >= ?
                       ORDER BY timestamp ASC, id ASC""",
                    (session_id, start_ts),
                ).fetchall()

            return [
                {"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]}
                for r in rows
            ]
        finally:
            conn.close()

    def delete_handoff_record(self, rating_id: int) -> bool:
        """Delete a single staff rating record by its ID."""
        conn = self._get_connection()
        try:
            cur = conn.execute("DELETE FROM staff_ratings WHERE id = ?", (rating_id,))
            conn.commit()
            return cur.rowcount > 0
        except Exception:
            logger.exception("Failed to delete handoff record %s", rating_id)
            raise
        finally:
            conn.close()

    def delete_all_handoff_records(self, days: int = 0) -> dict:
        """Delete all staff ratings and clear handoff claims for archived sessions.

        If *days* > 0, only deletes records older than that many days.
        Returns counts of deleted ratings and cleared sessions.
        """
        conn = self._get_connection()
        try:
            if days > 0:
                cutoff = time.time() - (days * 86400)
                sids = [r["session_id"] for r in conn.execute(
                    "SELECT session_id FROM sessions WHERE handoff_claimed_by IS NOT NULL AND handoff_active = 0 AND last_activity < ?",
                    (cutoff,),
                ).fetchall()]
            else:
                sids = [r["session_id"] for r in conn.execute(
                    "SELECT session_id FROM sessions WHERE handoff_claimed_by IS NOT NULL AND handoff_active = 0"
                ).fetchall()]

            if not sids:
                return {"deleted_ratings": 0, "cleared_sessions": 0}

            ph = ",".join("?" for _ in sids)
            rating_count = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM staff_ratings WHERE session_id IN ({ph})", sids,
            ).fetchone()["cnt"]
            conn.execute(f"DELETE FROM staff_ratings WHERE session_id IN ({ph})", sids)
            conn.execute(
                f"UPDATE sessions SET handoff_claimed_by = NULL WHERE session_id IN ({ph})", sids,
            )
            conn.commit()
            return {"deleted_ratings": rating_count, "cleared_sessions": len(sids)}
        except Exception:
            logger.exception("Failed to delete handoff records")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Live chat history
    # ------------------------------------------------------------------

    def get_live_chat_history(
        self, page: int = 1, page_size: int = 20, staff: str | None = None, days: int = 30,
    ) -> dict:
        """Return completed live chat sessions with message counts and ratings."""
        page = max(1, page)
        page_size = max(1, page_size)
        cutoff = time.time() - (days * 86400)
        conn = self._get_connection()
        try:
            where = "WHERE lc.status = 'ended' AND lc.created_at >= ?"
            params: list = [cutoff]
            if staff:
                where += " AND lc.staff_username = ?"
                params.append(staff)

            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM live_chat_sessions lc {where}", params,
            ).fetchone()["cnt"]

            rows = conn.execute(
                f"""SELECT lc.id, lc.parent_session_id, lc.staff_username, lc.status,
                           lc.created_at, lc.claimed_at, lc.ended_at,
                           s.display_name,
                           (SELECT COUNT(*) FROM live_chat_messages WHERE live_chat_id = lc.id) AS msg_count,
                           sr.rating
                    FROM live_chat_sessions lc
                    LEFT JOIN sessions s ON s.session_id = lc.parent_session_id
                    LEFT JOIN staff_ratings sr ON sr.session_id = lc.parent_session_id
                    {where}
                    ORDER BY lc.ended_at DESC
                    LIMIT ? OFFSET ?""",
                params + [page_size, (page - 1) * page_size],
            ).fetchall()

            entries = [
                {
                    "live_chat_id": r["id"],
                    "session_id": r["parent_session_id"],
                    "display_name": r["display_name"] or "",
                    "handled_by": r["staff_username"] or "—",
                    "created_at": r["created_at"],
                    "claimed_at": r["claimed_at"],
                    "ended_at": r["ended_at"],
                    "msg_count": r["msg_count"],
                    "rating": r["rating"],
                }
                for r in rows
            ]
            return {"sessions": entries, "total": total, "page": page, "page_size": page_size}
        finally:
            conn.close()

    def delete_live_chat_history(self, days: int = 0) -> dict:
        """Delete ended live chat sessions and their messages."""
        conn = self._get_connection()
        try:
            where = "WHERE status = 'ended'"
            params: list = []
            if days > 0:
                cutoff = time.time() - (days * 86400)
                where += " AND ended_at < ?"
                params.append(cutoff)

            ids = [r["id"] for r in conn.execute(
                f"SELECT id FROM live_chat_sessions {where}", params,
            ).fetchall()]
            if not ids:
                return {"deleted": 0}

            ph = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM live_chat_messages WHERE live_chat_id IN ({ph})", ids)
            conn.execute(f"DELETE FROM live_chat_sessions WHERE id IN ({ph})", ids)
            conn.commit()
            return {"deleted": len(ids)}
        except Exception:
            logger.exception("Failed to delete live chat history")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def _session_status(self, last_activity: float) -> str:
        """Return ``"active"`` or ``"expired"`` based on *last_activity*."""
        return "active" if time.time() - last_activity < SESSION_TIMEOUT else "expired"

    def get_sessions(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        search: str | None = None,
    ) -> SessionListResponse:
        """Return a paginated, optionally filtered list of session summaries.

        Parameters
        ----------
        page:
            1-based page number.  Clamped to >= 1.
        page_size:
            Number of results per page.  Clamped to >= 1.
        status:
            Optional filter: ``"active"`` or ``"expired"``.
        search:
            Optional keyword — only sessions containing a message with this
            substring are returned.
        """
        page = max(1, page)
        page_size = max(1, page_size)

        conn = self._get_connection()
        try:
            # Build the base query depending on whether a search filter is active.
            if search:
                base = """
                    FROM sessions s
                    WHERE s.session_id IN (
                        SELECT DISTINCT m.session_id FROM messages m
                        WHERE m.content LIKE ?
                    )
                """
                params: list = [f"%{search}%"]
            else:
                base = "FROM sessions s"
                params = []

            # Fetch all matching sessions (we need to compute status in Python).
            rows = conn.execute(
                f"SELECT s.session_id, s.created_at, s.last_activity, s.message_count, s.display_name {base} ORDER BY s.last_activity DESC",
                params,
            ).fetchall()

            # Compute status and apply status filter.
            summaries = [
                SessionSummary(
                    session_id=r["session_id"],
                    created_at=r["created_at"],
                    last_activity=r["last_activity"],
                    message_count=r["message_count"],
                    status=self._session_status(r["last_activity"]),
                    display_name=r["display_name"] or "",
                )
                for r in rows
            ]

            if status:
                summaries = [s for s in summaries if s.status == status]

            total = len(summaries)
            start = (page - 1) * page_size
            page_items = summaries[start : start + page_size]

            return SessionListResponse(
                sessions=page_items,
                total=total,
                page=page,
                page_size=page_size,
            )
        finally:
            conn.close()

    def get_session(self, session_id: str) -> SessionDetail | None:
        """Return full session detail including messages, or ``None`` if not found."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT session_id, created_at, last_activity, message_count, display_name FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None

            msg_rows = conn.execute(
                "SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY timestamp ASC, id ASC",
                (session_id,),
            ).fetchall()

            messages = [
                MessageRecord(role=m["role"], content=m["content"], timestamp=m["timestamp"])
                for m in msg_rows
            ]

            return SessionDetail(
                session_id=row["session_id"],
                created_at=row["created_at"],
                last_activity=row["last_activity"],
                message_count=row["message_count"],
                status=self._session_status(row["last_activity"]),
                display_name=row["display_name"] or "",
                messages=messages,
            )
        finally:
            conn.close()

    def get_stats(self) -> SessionStatsResponse:
        """Return aggregate session and message statistics."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT last_activity FROM sessions"
            ).fetchall()

            total_sessions = len(rows)
            active = sum(1 for r in rows if self._session_status(r["last_activity"]) == "active")
            expired = total_sessions - active

            total_messages = conn.execute(
                "SELECT COALESCE(SUM(message_count), 0) AS total FROM sessions"
            ).fetchone()["total"]

            return SessionStatsResponse(
                total_sessions=total_sessions,
                total_messages=total_messages,
                active_sessions=active,
                expired_sessions=expired,
            )
        finally:
            conn.close()

    def search_sessions(self, keyword: str) -> list[SessionSummary]:
        """Return sessions containing *keyword* in any message content.

        This is a convenience wrapper around :meth:`get_sessions` that
        returns an unpaginated list.
        """
        if not keyword:
            return []

        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT s.session_id, s.created_at, s.last_activity, s.message_count
                FROM sessions s
                JOIN messages m ON m.session_id = s.session_id
                WHERE m.content LIKE ?
                ORDER BY s.last_activity DESC
                """,
                (f"%{keyword}%",),
            ).fetchall()

            return [
                SessionSummary(
                    session_id=r["session_id"],
                    created_at=r["created_at"],
                    last_activity=r["last_activity"],
                    message_count=r["message_count"],
                    status=self._session_status(r["last_activity"]),
                )
                for r in rows
            ]
        finally:
            conn.close()

    def get_analytics(self, days: int = 30) -> AnalyticsResponse:
        """Return analytics data for the admin dashboard."""
        cutoff = time.time() - (days * 86400)
        conn = self._get_connection()
        try:
            # Single query: get all user messages in period with their metadata
            rows = conn.execute(
                """
                SELECT COALESCE(intent, 'unknown') AS intent,
                       CAST(strftime('%H', timestamp, 'unixepoch', 'localtime') AS INTEGER) AS hour,
                       CAST(strftime('%w', timestamp, 'unixepoch', 'localtime') AS INTEGER) AS dow
                FROM messages
                WHERE role = 'user' AND timestamp >= ?
                """,
                (cutoff,),
            ).fetchall()

            # Process in Python (single pass)
            intent_counts: dict[str, int] = {}
            hour_counts: dict[int, int] = {}
            dow_counts: dict[int, int] = {}
            failed = 0
            total_user = len(rows)

            for r in rows:
                intent = r["intent"]
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
                hour_counts[r["hour"]] = hour_counts.get(r["hour"], 0) + 1
                dow_counts[r["dow"]] = dow_counts.get(r["dow"], 0) + 1
                if intent in ("unclear", "catalog_vague"):
                    failed += 1

            # Also count non-user messages for hourly/daily (quick second query)
            other_rows = conn.execute(
                """
                SELECT CAST(strftime('%H', timestamp, 'unixepoch', 'localtime') AS INTEGER) AS hour,
                       CAST(strftime('%w', timestamp, 'unixepoch', 'localtime') AS INTEGER) AS dow
                FROM messages
                WHERE role != 'user' AND timestamp >= ?
                """,
                (cutoff,),
            ).fetchall()
            for r in other_rows:
                hour_counts[r["hour"]] = hour_counts.get(r["hour"], 0) + 1
                dow_counts[r["dow"]] = dow_counts.get(r["dow"], 0) + 1

            intent_breakdown = sorted(
                [IntentCount(intent=k, count=v) for k, v in intent_counts.items()],
                key=lambda x: x.count, reverse=True,
            )
            hourly_activity = [HourlyActivity(hour=h, count=hour_counts.get(h, 0)) for h in range(24)]
            day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            daily_activity = [DailyActivity(day=day_names[d], count=dow_counts.get(d, 0)) for d in range(7)]

            # Average messages per session
            avg_row = conn.execute(
                "SELECT AVG(message_count) AS avg_msgs FROM sessions WHERE created_at >= ?",
                (cutoff,),
            ).fetchone()
            avg_messages = round(avg_row["avg_msgs"] or 0.0, 1)

            return AnalyticsResponse(
                intent_breakdown=intent_breakdown,
                hourly_activity=hourly_activity,
                daily_activity=daily_activity,
                avg_messages_per_session=avg_messages,
                failed_queries=failed,
                total_user_messages=total_user,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Feedback operations
    # ------------------------------------------------------------------

    def save_feedback(
        self, session_id: str, message_timestamp: float, rating: int
    ) -> None:
        """Save patron feedback (thumbs up/down) for a bot response."""
        conn = self._get_connection()
        try:
            # Upsert: one rating per session+message_timestamp pair
            conn.execute(
                """
                INSERT INTO feedback (session_id, message_timestamp, rating, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (session_id, message_timestamp, rating, time.time()),
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to save feedback for session %s", session_id)
            raise
        finally:
            conn.close()

    def get_feedback_stats(self, days: int = 30) -> FeedbackStats:
        """Return aggregate feedback statistics."""
        cutoff = time.time() - (days * 86400)
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT rating, COUNT(*) AS cnt FROM feedback WHERE created_at >= ? GROUP BY rating",
                (cutoff,),
            ).fetchall()
            positive = 0
            negative = 0
            for r in rows:
                if r["rating"] == 1:
                    positive = r["cnt"]
                elif r["rating"] == -1:
                    negative = r["cnt"]
            total = positive + negative
            rate = round((positive / total) * 100, 1) if total > 0 else 0.0
            return FeedbackStats(
                total_ratings=total,
                positive=positive,
                negative=negative,
                satisfaction_rate=rate,
            )
        finally:
            conn.close()

    def get_recent_feedback(
        self, days: int = 30, rating_filter: int | None = None,
        page: int = 1, page_size: int = 20,
    ) -> list[FeedbackEntry]:
        """Return recent feedback entries with surrounding message context."""
        cutoff = time.time() - (days * 86400)
        conn = self._get_connection()
        try:
            query = """
                SELECT f.session_id, f.message_timestamp, f.rating, f.created_at
                FROM feedback f
                WHERE f.created_at >= ?
            """
            params: list = [cutoff]
            if rating_filter is not None:
                query += " AND f.rating = ?"
                params.append(rating_filter)
            query += " ORDER BY f.created_at DESC LIMIT ? OFFSET ?"
            params.extend([page_size, (page - 1) * page_size])

            rows = conn.execute(query, params).fetchall()
            entries = []
            for r in rows:
                # Find the assistant message at this timestamp
                assistant_msg = conn.execute(
                    "SELECT content FROM messages WHERE session_id = ? AND role = 'assistant' AND ABS(timestamp - ?) < 1 LIMIT 1",
                    (r["session_id"], r["message_timestamp"]),
                ).fetchone()
                # Find the preceding user message
                user_msg = conn.execute(
                    "SELECT content FROM messages WHERE session_id = ? AND role = 'user' AND timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
                    (r["session_id"], r["message_timestamp"]),
                ).fetchone()
                entries.append(FeedbackEntry(
                    session_id=r["session_id"],
                    user_message=user_msg["content"] if user_msg else "",
                    assistant_message=assistant_msg["content"] if assistant_msg else "",
                    rating=r["rating"],
                    timestamp=r["created_at"],
                ))
            return entries
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Staff rating operations
    # ------------------------------------------------------------------

    def save_staff_rating(self, session_id: str, staff_username: str, rating: int) -> None:
        """Save a patron's rating for the staff member who handled their handoff."""
        conn = self._get_connection()
        try:
            # Get current handoff number
            row = conn.execute(
                "SELECT COALESCE(handoff_count, 1) AS cnt FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            handoff_num = row["cnt"] if row else 1

            conn.execute(
                """INSERT INTO staff_ratings (session_id, handoff_num, staff_username, rating, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(session_id, handoff_num) DO UPDATE SET rating = excluded.rating, created_at = excluded.created_at""",
                (session_id, handoff_num, staff_username, rating, time.time()),
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to save staff rating for session %s", session_id)
            raise
        finally:
            conn.close()

    def get_staff_ratings_summary(self, days: int = 30) -> list[dict]:
        """Return per-staff rating stats: total, positive, negative, avg."""
        cutoff = time.time() - (days * 86400)
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT staff_username,
                       COUNT(*) AS total,
                       SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS positive,
                       SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) AS negative
                FROM staff_ratings
                WHERE created_at >= ?
                GROUP BY staff_username
                ORDER BY total DESC
                """,
                (cutoff,),
            ).fetchall()
            return [
                {
                    "staff_username": r["staff_username"],
                    "total": r["total"],
                    "positive": r["positive"],
                    "negative": r["negative"],
                    "satisfaction_rate": round((r["positive"] / r["total"]) * 100, 1) if r["total"] > 0 else 0.0,
                }
                for r in rows
            ]
        finally:
            conn.close()

    def get_staff_rating_details(self, staff_username: str, days: int = 30, page: int = 1, page_size: int = 20) -> dict:
        """Return individual ratings for a specific staff member."""
        cutoff = time.time() - (days * 86400)
        page = max(1, page)
        page_size = max(1, page_size)
        conn = self._get_connection()
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS cnt FROM staff_ratings WHERE staff_username = ? AND created_at >= ?",
                (staff_username, cutoff),
            ).fetchone()["cnt"]
            rows = conn.execute(
                """SELECT sr.session_id, sr.rating, sr.created_at
                   FROM staff_ratings sr
                   WHERE sr.staff_username = ? AND sr.created_at >= ?
                   ORDER BY sr.created_at DESC
                   LIMIT ? OFFSET ?""",
                (staff_username, cutoff, page_size, (page - 1) * page_size),
            ).fetchall()
            return {
                "ratings": [
                    {"session_id": r["session_id"], "rating": r["rating"], "created_at": r["created_at"]}
                    for r in rows
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Unanswered query operations
    # ------------------------------------------------------------------

    def get_unanswered_queries(
        self, page: int = 1, page_size: int = 20, days: int = 30,
    ) -> UnansweredQueueResponse:
        """Return user messages classified as unclear or catalog_vague."""
        cutoff = time.time() - (days * 86400)
        page = max(1, page)
        page_size = max(1, page_size)
        conn = self._get_connection()
        try:
            total_row = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM messages
                WHERE role = 'user' AND timestamp >= ?
                  AND intent IN ('unclear', 'catalog_vague')
                """,
                (cutoff,),
            ).fetchone()
            total = total_row["cnt"]

            rows = conn.execute(
                """
                SELECT session_id, content, intent, timestamp
                FROM messages
                WHERE role = 'user' AND timestamp >= ?
                  AND intent IN ('unclear', 'catalog_vague')
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (cutoff, page_size, (page - 1) * page_size),
            ).fetchall()

            queries = [
                UnansweredQuery(
                    session_id=r["session_id"],
                    content=r["content"],
                    intent=r["intent"],
                    timestamp=r["timestamp"],
                    resolved=False,
                )
                for r in rows
            ]
            return UnansweredQueueResponse(
                queries=queries, total=total, page=page, page_size=page_size,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Session flagging
    # ------------------------------------------------------------------

    def flag_session(self, session_id: str, note: str) -> None:
        """Add or update a flag/note on a session."""
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO session_flags (session_id, note, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET note = excluded.note, created_at = excluded.created_at
                """,
                (session_id, note, time.time()),
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to flag session %s", session_id)
            raise
        finally:
            conn.close()

    def unflag_session(self, session_id: str) -> None:
        """Remove a flag from a session."""
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM session_flags WHERE session_id = ?", (session_id,))
            conn.commit()
        except Exception:
            logger.exception("Failed to unflag session %s", session_id)
            raise
        finally:
            conn.close()

    def get_flagged_sessions(self, page: int = 1, page_size: int = 20) -> dict:
        """Return paginated flagged sessions with their notes."""
        page = max(1, page)
        page_size = max(1, page_size)
        conn = self._get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM session_flags").fetchone()["cnt"]
            rows = conn.execute(
                """
                SELECT sf.session_id, sf.note, sf.created_at,
                       s.created_at AS session_created, s.last_activity, s.message_count
                FROM session_flags sf
                JOIN sessions s ON s.session_id = sf.session_id
                ORDER BY sf.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, (page - 1) * page_size),
            ).fetchall()
            flags = [
                {
                    "session_id": r["session_id"],
                    "note": r["note"],
                    "flagged_at": r["created_at"],
                    "session_created": r["session_created"],
                    "last_activity": r["last_activity"],
                    "message_count": r["message_count"],
                    "status": self._session_status(r["last_activity"]),
                }
                for r in rows
            ]
            return {"flags": flags, "total": total, "page": page, "page_size": page_size}
        finally:
            conn.close()

    def get_session_flag(self, session_id: str) -> SessionFlag | None:
        """Return the flag for a session, or None."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT session_id, note, created_at FROM session_flags WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return SessionFlag(session_id=row["session_id"], note=row["note"], created_at=row["created_at"])
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Bulk cleanup
    # ------------------------------------------------------------------

    def bulk_delete_expired(self, older_than_days: int = 30) -> BulkCleanupResponse:
        """Delete expired sessions older than the given number of days."""
        cutoff = time.time() - (older_than_days * 86400)
        conn = self._get_connection()
        try:
            # Find expired sessions older than cutoff
            rows = conn.execute(
                "SELECT session_id FROM sessions WHERE last_activity < ? AND last_activity < ?",
                (time.time() - SESSION_TIMEOUT, cutoff),
            ).fetchall()
            session_ids = [r["session_id"] for r in rows]
            if not session_ids:
                return BulkCleanupResponse(deleted_sessions=0, deleted_messages=0)

            placeholders = ",".join("?" for _ in session_ids)
            msg_count = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM messages WHERE session_id IN ({placeholders})",
                session_ids,
            ).fetchone()["cnt"]

            # Delete live chat data first (foreign key order)
            lc_ids = [r["id"] for r in conn.execute(
                f"SELECT id FROM live_chat_sessions WHERE parent_session_id IN ({placeholders})",
                session_ids,
            ).fetchall()]
            if lc_ids:
                lc_ph = ",".join("?" for _ in lc_ids)
                conn.execute(f"DELETE FROM live_chat_messages WHERE live_chat_id IN ({lc_ph})", lc_ids)
                conn.execute(f"DELETE FROM live_chat_sessions WHERE id IN ({lc_ph})", lc_ids)

            conn.execute(f"DELETE FROM staff_ratings WHERE session_id IN ({placeholders})", session_ids)
            conn.execute(f"DELETE FROM feedback WHERE session_id IN ({placeholders})", session_ids)
            conn.execute(f"DELETE FROM session_flags WHERE session_id IN ({placeholders})", session_ids)
            conn.execute(f"DELETE FROM messages WHERE session_id IN ({placeholders})", session_ids)
            conn.execute(f"DELETE FROM sessions WHERE session_id IN ({placeholders})", session_ids)
            conn.commit()

            return BulkCleanupResponse(deleted_sessions=len(session_ids), deleted_messages=msg_count)
        except Exception:
            logger.exception("Failed to bulk delete expired sessions")
            raise
        finally:
            conn.close()

    def delete_all_sessions(self) -> BulkCleanupResponse:
        """Delete every session and all associated data."""
        conn = self._get_connection()
        try:
            msg_count = conn.execute("SELECT COUNT(*) AS cnt FROM messages").fetchone()["cnt"]
            sess_count = conn.execute("SELECT COUNT(*) AS cnt FROM sessions").fetchone()["cnt"]
            # Delete in foreign key order
            conn.execute("DELETE FROM live_chat_messages")
            conn.execute("DELETE FROM live_chat_sessions")
            conn.execute("DELETE FROM staff_ratings")
            conn.execute("DELETE FROM feedback")
            conn.execute("DELETE FROM session_flags")
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM sessions")
            conn.commit()
            return BulkCleanupResponse(deleted_sessions=sess_count, deleted_messages=msg_count)
        except Exception:
            logger.exception("Failed to delete all sessions")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def export_sessions_csv(self, status: str | None = None, days: int | None = None) -> str:
        """Export sessions and their messages as CSV text."""
        import csv
        import io
        from datetime import datetime, timezone

        def fmt_ts(ts):
            """Format a unix timestamp as a readable datetime string."""
            if not ts:
                return ""
            try:
                return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError, OSError):
                return str(ts)

        conn = self._get_connection()
        try:
            query = """
                SELECT s.session_id, s.created_at, s.last_activity, s.message_count,
                       m.role, m.content, m.timestamp AS msg_timestamp, m.intent
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.session_id
            """
            conditions = []
            params: list = []
            if days:
                cutoff = time.time() - (days * 86400)
                conditions.append("s.created_at >= ?")
                params.append(cutoff)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY s.last_activity DESC, m.timestamp ASC"

            rows = conn.execute(query, params).fetchall()

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "session_id", "session_created", "last_activity", "message_count",
                "status", "role", "content", "message_timestamp", "intent",
            ])
            for r in rows:
                sess_status = self._session_status(r["last_activity"])
                if status and sess_status != status:
                    continue
                # Sanitize content: strip non-printable characters
                content = r["content"] or ""
                content = "".join(c for c in content if c.isprintable() or c in "\n\r\t")
                writer.writerow([
                    r["session_id"],
                    fmt_ts(r["created_at"]),
                    fmt_ts(r["last_activity"]),
                    r["message_count"],
                    sess_status,
                    r["role"] or "",
                    content,
                    fmt_ts(r["msg_timestamp"]),
                    r["intent"] or "",
                ])
            return output.getvalue()
        finally:
            conn.close()
