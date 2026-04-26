"""API call statistics tracker with SQLite storage and ASGI middleware."""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import threading
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = logging.getLogger("twapi.stats")

# Absolute path to DB (no longer depends on cwd)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_stats.db")

# Paths to exclude from tracking (internal / static)
_SKIP_PATHS = {"/docs", "/openapi.json", "/redoc", "/favicon.ico", "/dashboard"}


class StatsTracker:
    """Thread-safe API statistics recorder backed by SQLite."""

    def __init__(self) -> None:
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def init_db(self) -> None:
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS api_calls (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                method      TEXT    NOT NULL,
                path        TEXT    NOT NULL,
                endpoint    TEXT    NOT NULL DEFAULT '',
                query       TEXT    NOT NULL DEFAULT '',
                status_code INTEGER NOT NULL,
                latency_ms  REAL    NOT NULL,
                client_ip   TEXT    NOT NULL DEFAULT '',
                user_agent  TEXT    NOT NULL DEFAULT '',
                error       TEXT    NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_calls_ts   ON api_calls(timestamp);
            CREATE INDEX IF NOT EXISTS idx_calls_ep   ON api_calls(endpoint);
            CREATE INDEX IF NOT EXISTS idx_calls_code ON api_calls(status_code);
        """)
        conn.commit()

    def record(
        self,
        *,
        method: str,
        path: str,
        query: str,
        status_code: int,
        latency_ms: float,
        client_ip: str = "",
        user_agent: str = "",
        error: str = "",
    ) -> None:
        endpoint = _classify_endpoint(path)
        ts = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        conn.execute(
            """INSERT INTO api_calls
               (timestamp, method, path, endpoint, query, status_code,
                latency_ms, client_ip, user_agent, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, method, path, endpoint, query, status_code,
             round(latency_ms, 2), client_ip, user_agent, error),
        )
        conn.commit()

    def get_summary(self, *, hours: int = 24) -> dict:
        conn = self._conn()
        rows = conn.execute(
            """SELECT
                 COUNT(*)                                     AS total_calls,
                 SUM(CASE WHEN status_code < 400 THEN 1 ELSE 0 END) AS success,
                 SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors,
                 ROUND(AVG(latency_ms), 1)                   AS avg_latency_ms,
                 ROUND(MIN(latency_ms), 1)                   AS min_latency_ms,
                 ROUND(MAX(latency_ms), 1)                   AS max_latency_ms
               FROM api_calls
               WHERE timestamp >= datetime('now', ?)""",
            (f"-{hours} hours",),
        ).fetchone()

        by_endpoint = conn.execute(
            """SELECT endpoint,
                      COUNT(*) AS calls,
                      SUM(CASE WHEN status_code < 400 THEN 1 ELSE 0 END) AS success,
                      ROUND(AVG(latency_ms), 1) AS avg_ms
               FROM api_calls
               WHERE timestamp >= datetime('now', ?)
               GROUP BY endpoint ORDER BY calls DESC""",
            (f"-{hours} hours",),
        ).fetchall()

        by_status = conn.execute(
            """SELECT status_code, COUNT(*) AS count
               FROM api_calls
               WHERE timestamp >= datetime('now', ?)
               GROUP BY status_code ORDER BY count DESC""",
            (f"-{hours} hours",),
        ).fetchall()

        by_hour = conn.execute(
            """SELECT strftime('%Y-%m-%dT%H:00:00', timestamp) AS hour,
                      COUNT(*) AS calls,
                      ROUND(AVG(latency_ms), 1) AS avg_ms,
                      SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors
               FROM api_calls
               WHERE timestamp >= datetime('now', ?)
               GROUP BY hour ORDER BY hour""",
            (f"-{hours} hours",),
        ).fetchall()

        top_paths = conn.execute(
            """SELECT path, COUNT(*) AS calls
               FROM api_calls
               WHERE timestamp >= datetime('now', ?)
               GROUP BY path ORDER BY calls DESC LIMIT 20""",
            (f"-{hours} hours",),
        ).fetchall()

        total = dict(rows) if rows else {}
        success_rate = 0.0
        if total.get("total_calls", 0) > 0:
            success_rate = round(total["success"] / total["total_calls"] * 100, 1)

        return {
            "period_hours": hours,
            "total_calls": total.get("total_calls", 0),
            "success_count": total.get("success", 0),
            "error_count": total.get("errors", 0),
            "success_rate": success_rate,
            "avg_latency_ms": total.get("avg_latency_ms", 0),
            "min_latency_ms": total.get("min_latency_ms", 0),
            "max_latency_ms": total.get("max_latency_ms", 0),
            "by_endpoint": [dict(r) for r in by_endpoint],
            "by_status_code": [dict(r) for r in by_status],
            "by_hour": [dict(r) for r in by_hour],
            "top_paths": [dict(r) for r in top_paths],
        }

    def get_recent(self, *, limit: int = 50) -> list[dict]:
        """Return recent calls with sensitive fields redacted."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT timestamp, method, path, endpoint, query,
                      status_code, latency_ms, error
               FROM api_calls ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def _classify_endpoint(path: str) -> str:
    """Map a request path to a human-readable endpoint name."""
    if path == "/" or path == "":
        return "root"
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "api":
        if parts[1] == "health":
            return "health"
        if parts[1] == "search":
            if len(parts) >= 3 and parts[2] == "users":
                return "search/users"
            return "search"
        if parts[1] == "stats":
            return "stats" if len(parts) == 2 else "stats/" + parts[2]
        if parts[1] == "user":
            if len(parts) == 3:
                return "user/profile"
            if len(parts) >= 4:
                return f"user/{parts[3]}"
        if parts[1] == "tweet":
            return "tweet/detail"
    return path


class StatsMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that records every API call."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Skip non-API paths
        if path in _SKIP_PATHS or path.startswith("/dashboard"):
            return await call_next(request)

        t0 = time.monotonic()
        error_msg = ""
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            error_msg = str(exc)[:200]
            raise
        finally:
            latency = (time.monotonic() - t0) * 1000
            try:
                stats_tracker.record(
                    method=request.method,
                    path=path,
                    query=str(request.url.query) if request.url.query else "",
                    status_code=status_code,
                    latency_ms=latency,
                    client_ip=request.client.host if request.client else "",
                    user_agent=request.headers.get("user-agent", "")[:200],
                    error=error_msg,
                )
            except Exception:
                log.error("Failed to record stats for %s %s", request.method, path, exc_info=True)


stats_tracker = StatsTracker()
