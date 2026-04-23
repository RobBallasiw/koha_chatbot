"""Database connection factory — uses Turso HTTP API when configured, falls back to sqlite3.

Turso's HTTP API is used instead of libsql-experimental to avoid native binary
issues on serverless platforms like Vercel.
"""

import logging
import os
import sqlite3

import httpx

logger = logging.getLogger(__name__)

_TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
_TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
_USE_TURSO = bool(_TURSO_URL and _TURSO_TOKEN)


def _turso_http_url() -> str:
    """Convert libsql:// URL to https:// for the HTTP API."""
    url = _TURSO_URL
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    elif url.startswith("ws://"):
        url = "http://" + url[len("ws://"):]
    elif url.startswith("wss://"):
        url = "https://" + url[len("wss://"):]
    return url.rstrip("/")


class TursoRow:
    """Dict-like row that supports both index and key access."""

    def __init__(self, columns: list[str], values: list):
        self._columns = columns
        self._values = values
        self._map = dict(zip(columns, values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def __contains__(self, key):
        return key in self._map

    def keys(self):
        return self._columns


class TursoResultSet:
    """Mimics sqlite3 cursor result for fetchall/fetchone."""

    def __init__(self, columns: list[str], rows: list[list]):
        self._columns = columns
        self._rows = [TursoRow(columns, r) for r in rows]
        self._iter = iter(self._rows)
        self.rowcount = len(rows)
        self.lastrowid = None

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)

    def __next__(self):
        return next(self._iter)


# Shared httpx client for Turso connections (avoids creating new TCP connections per request)
_turso_client: httpx.Client | None = None


def _get_turso_client() -> httpx.Client:
    global _turso_client
    if _turso_client is None:
        _turso_client = httpx.Client(timeout=30.0)
    return _turso_client


class TursoConnection:
    """SQLite-compatible connection wrapper that talks to Turso via HTTP API."""

    def __init__(self, base_url: str, auth_token: str):
        self._base_url = base_url
        self._auth_token = auth_token
        self._client = _get_turso_client()
        self.row_factory = None  # compatibility

    def _execute_batch(self, statements: list[dict]) -> list[dict]:
        """Execute a batch of statements via Turso HTTP API."""
        url = f"{self._base_url}/v3/pipeline"
        body = {"requests": statements}
        headers = {"Authorization": f"Bearer {self._auth_token}"}
        resp = self._client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json().get("results", [])

    def _make_stmt(self, sql: str, params=None) -> dict:
        """Build a Turso pipeline request for a single statement."""
        stmt: dict = {"type": "execute", "stmt": {"sql": sql}}
        if params:
            args = []
            for p in params:
                if p is None:
                    args.append({"type": "null"})
                elif isinstance(p, int):
                    args.append({"type": "integer", "value": str(p)})
                elif isinstance(p, float):
                    args.append({"type": "float", "value": p})
                elif isinstance(p, str):
                    args.append({"type": "text", "value": p})
                else:
                    args.append({"type": "text", "value": str(p)})
            stmt["stmt"]["args"] = args
        return stmt

    def _parse_result(self, result: dict) -> TursoResultSet:
        """Parse a Turso HTTP API result into a TursoResultSet."""
        resp = result.get("response", {})
        res_type = resp.get("type", "")
        if res_type == "execute":
            res = resp.get("result", {})
            cols_raw = res.get("cols", [])
            columns = [c.get("name", f"col{i}") for i, c in enumerate(cols_raw)]
            rows_raw = res.get("rows", [])
            rows = []
            for row in rows_raw:
                vals = []
                for cell in row:
                    t = cell.get("type", "null")
                    if t == "null":
                        vals.append(None)
                    elif t == "integer":
                        vals.append(int(cell["value"]))
                    elif t == "float":
                        vals.append(float(cell["value"]))
                    else:
                        vals.append(cell.get("value", ""))
                rows.append(vals)
            rs = TursoResultSet(columns, rows)
            rs.rowcount = res.get("affected_row_count", len(rows))
            rs.lastrowid = res.get("last_insert_rowid")
            return rs
        return TursoResultSet([], [])

    def execute(self, sql: str, params=None) -> TursoResultSet:
        """Execute a single SQL statement."""
        stmt = self._make_stmt(sql, params)
        results = self._execute_batch([stmt])
        if results:
            return self._parse_result(results[0])
        return TursoResultSet([], [])

    def executescript(self, script: str):
        """Execute multiple SQL statements separated by semicolons."""
        statements = [s.strip() for s in script.split(";") if s.strip()]
        batch = [self._make_stmt(s) for s in statements]
        if batch:
            self._execute_batch(batch)

    def cursor(self):
        """Return self as cursor (compatibility)."""
        return self

    def commit(self):
        """No-op — Turso auto-commits."""
        pass

    def close(self):
        """No-op — HTTP connections are stateless."""
        pass


# --- Public API ---

def get_connection(db_path: str = "/tmp/sessions.db"):
    """Return a database connection.

    Uses Turso HTTP API when TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set,
    otherwise uses local sqlite3.
    """
    if _USE_TURSO:
        return TursoConnection(_turso_http_url(), _TURSO_TOKEN)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def sync_if_needed(conn):
    """No-op — kept for compatibility. Turso HTTP API auto-commits."""
    pass


# Re-export for type references
libsql = sqlite3
