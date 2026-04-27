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
