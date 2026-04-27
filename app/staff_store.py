"""Turso/SQLite-backed storage for dashboard settings."""

import logging
import os
import time
from pathlib import Path

from app.db import get_connection, sync_if_needed

logger = logging.getLogger(__name__)


class StaffStore:
    """Manages dashboard feature settings in SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.environ.get("SESSION_DB_PATH", "/tmp/sessions.db")
        self._init_tables()

    def _get_connection(self):
        conn = get_connection(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        return conn

    def _init_tables(self) -> None:
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        conn = self._get_connection()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS dashboard_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS staff_contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                );
            """)
            conn.commit()
            self._seed_defaults(conn)
        finally:
            conn.close()

    def _seed_defaults(self, conn: object) -> None:
        """Insert default settings if the table is empty."""
        count = conn.execute("SELECT COUNT(*) AS cnt FROM dashboard_settings").fetchone()["cnt"]
        if count > 0:
            return
        defaults = {
            "feature_analytics": "true",
            "feature_quality": "true",
            "feature_library_info": "true",
            "feature_management": "true",
            "feature_live_chat": "true",
            "feature_staff_performance": "true",
            "session_timeout_minutes": "5",
            "max_messages_per_session": "20",
        }
        now = time.time()
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO dashboard_settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )
        conn.commit()

    # ------------------------------------------------------------------
    # Dashboard settings operations
    # ------------------------------------------------------------------

    def get_all_settings(self) -> dict[str, str]:
        """Return all settings as a key-value dict."""
        conn = self._get_connection()
        try:
            rows = conn.execute("SELECT key, value FROM dashboard_settings").fetchall()
            return {r["key"]: r["value"] for r in rows}
        finally:
            conn.close()

    def get_setting(self, key: str) -> str | None:
        """Return a single setting value, or None."""
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT value FROM dashboard_settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None
        finally:
            conn.close()

    def update_settings(self, settings: dict[str, str]) -> None:
        """Upsert multiple settings at once."""
        now = time.time()
        conn = self._get_connection()
        try:
            for key, value in settings.items():
                conn.execute(
                    """INSERT INTO dashboard_settings (key, value, updated_at) VALUES (?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                    (key, str(value), now),
                )
            conn.commit()
        finally:
            conn.close()

    def is_feature_enabled(self, feature_key: str) -> bool:
        """Check if a feature toggle is enabled."""
        val = self.get_setting(feature_key)
        return val == "true" if val is not None else True

    # ------------------------------------------------------------------
    # Staff contacts (name + email for notifications)
    # ------------------------------------------------------------------

    def list_contacts(self) -> list[dict]:
        """Return all staff contacts."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT id, name, email, is_active, created_at FROM staff_contacts ORDER BY created_at DESC"
            ).fetchall()
            return [
                {"id": r["id"], "name": r["name"], "email": r["email"],
                 "is_active": bool(r["is_active"]), "created_at": r["created_at"]}
                for r in rows
            ]
        finally:
            conn.close()

    def add_contact(self, name: str, email: str) -> dict:
        """Add a new staff contact. Raises ValueError if email already exists."""
        now = time.time()
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO staff_contacts (name, email, is_active, created_at) VALUES (?, ?, 1, ?)",
                (name.strip(), email.strip().lower(), now),
            )
            conn.commit()
            return {"name": name.strip(), "email": email.strip().lower(), "is_active": True}
        except Exception:
            raise ValueError(f"Email '{email}' already exists")
        finally:
            conn.close()

    def update_contact(self, contact_id: int, name: str | None = None, email: str | None = None, is_active: bool | None = None) -> bool:
        """Update a staff contact. Returns True if updated."""
        parts, params = [], []
        if name is not None:
            parts.append("name = ?")
            params.append(name.strip())
        if email is not None:
            parts.append("email = ?")
            params.append(email.strip().lower())
        if is_active is not None:
            parts.append("is_active = ?")
            params.append(1 if is_active else 0)
        if not parts:
            return False
        params.append(contact_id)
        conn = self._get_connection()
        try:
            cur = conn.execute(f"UPDATE staff_contacts SET {', '.join(parts)} WHERE id = ?", params)
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def delete_contact(self, contact_id: int) -> bool:
        """Delete a staff contact."""
        conn = self._get_connection()
        try:
            cur = conn.execute("DELETE FROM staff_contacts WHERE id = ?", (contact_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_active_contacts(self) -> list[dict]:
        """Return only active staff contacts (for notifications)."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT id, name, email FROM staff_contacts WHERE is_active = 1"
            ).fetchall()
            return [{"id": r["id"], "name": r["name"], "email": r["email"]} for r in rows]
        finally:
            conn.close()
