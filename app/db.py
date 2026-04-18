"""Database connection factory — uses Turso (libsql) when configured, falls back to sqlite3."""

import logging
import os

logger = logging.getLogger(__name__)

# Detect Turso configuration
_TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
_TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
_USE_TURSO = bool(_TURSO_URL and _TURSO_TOKEN)

if _USE_TURSO:
    try:
        import libsql_experimental as libsql  # type: ignore
        logger.info("Using Turso (libsql) for database connections")
    except ImportError:
        logger.warning("libsql_experimental not installed, falling back to sqlite3")
        import sqlite3 as libsql  # type: ignore
        _USE_TURSO = False
else:
    import sqlite3 as libsql  # type: ignore


def get_connection(db_path: str = "/tmp/sessions.db"):
    """Return a database connection with row_factory enabled.

    Uses Turso when TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set,
    otherwise uses local sqlite3.
    """
    if _USE_TURSO:
        conn = libsql.connect(
            db_path,
            sync_url=_TURSO_URL,
            auth_token=_TURSO_TOKEN,
        )
        conn.sync()
    else:
        conn = libsql.connect(db_path)

    conn.row_factory = libsql.Row
    return conn


def sync_if_needed(conn):
    """Call sync() on the connection if using Turso embedded replicas."""
    if _USE_TURSO and hasattr(conn, "sync"):
        try:
            conn.sync()
        except Exception:
            logger.warning("Failed to sync with Turso remote", exc_info=True)
