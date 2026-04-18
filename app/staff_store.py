"""SQLite-backed storage for staff accounts and dashboard settings."""

import hashlib
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _hash_password(password: str, salt: str) -> str:
    """Hash a password with the given salt using SHA-256."""
    return hashlib.sha256((salt + password).encode()).hexdigest()


class StaffStore:
    """Manages staff accounts and feature settings in SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.environ.get("SESSION_DB_PATH", "data/sessions.db")
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_tables(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_connection()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS staff_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'staff',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

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

    def _seed_defaults(self, conn: sqlite3.Connection) -> None:
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
    # Staff account operations
    # ------------------------------------------------------------------

    def create_staff(self, username: str, password: str, display_name: str = "", role: str = "staff") -> dict:
        """Create a new staff account. Returns the created account info."""
        salt = secrets.token_hex(16)
        password_hash = _hash_password(password, salt)
        now = time.time()
        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT INTO staff_accounts (username, display_name, password_hash, salt, role, is_active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (username.strip().lower(), display_name.strip(), password_hash, salt, role, now, now),
            )
            conn.commit()
            return {"username": username.strip().lower(), "display_name": display_name.strip(), "role": role, "is_active": True}
        except sqlite3.IntegrityError:
            raise ValueError(f"Username '{username}' already exists")
        finally:
            conn.close()

    def verify_staff(self, username: str, password: str) -> dict | None:
        """Verify staff credentials. Returns account info or None."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM staff_accounts WHERE username = ? AND is_active = 1",
                (username.strip().lower(),),
            ).fetchone()
            if not row:
                return None
            expected = _hash_password(password, row["salt"])
            if row["password_hash"] != expected:
                return None
            return {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "role": row["role"],
                "is_active": bool(row["is_active"]),
            }
        finally:
            conn.close()

    def list_staff(self) -> list[dict]:
        """Return all staff accounts (without password data)."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT id, username, display_name, role, is_active, created_at, updated_at FROM staff_accounts ORDER BY created_at DESC"
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "username": r["username"],
                    "display_name": r["display_name"],
                    "role": r["role"],
                    "is_active": bool(r["is_active"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def update_staff(self, staff_id: int, display_name: str | None = None, role: str | None = None, is_active: bool | None = None) -> bool:
        """Update a staff account. Returns True if a row was updated."""
        parts = []
        params: list = []
        if display_name is not None:
            parts.append("display_name = ?")
            params.append(display_name.strip())
        if role is not None:
            parts.append("role = ?")
            params.append(role)
        if is_active is not None:
            parts.append("is_active = ?")
            params.append(1 if is_active else 0)
        if not parts:
            return False
        parts.append("updated_at = ?")
        params.append(time.time())
        params.append(staff_id)
        conn = self._get_connection()
        try:
            cur = conn.execute(f"UPDATE staff_accounts SET {', '.join(parts)} WHERE id = ?", params)
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def reset_password(self, staff_id: int, new_password: str) -> bool:
        """Reset a staff member's password."""
        salt = secrets.token_hex(16)
        password_hash = _hash_password(new_password, salt)
        conn = self._get_connection()
        try:
            cur = conn.execute(
                "UPDATE staff_accounts SET password_hash = ?, salt = ?, updated_at = ? WHERE id = ?",
                (password_hash, salt, time.time(), staff_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def delete_staff(self, staff_id: int) -> bool:
        """Permanently delete a staff account."""
        conn = self._get_connection()
        try:
            cur = conn.execute("DELETE FROM staff_accounts WHERE id = ?", (staff_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

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
