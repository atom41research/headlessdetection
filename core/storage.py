"""Unified SQLite storage for detection results, probe sessions, and server signals.

Merges the two original storage modules:
- Detection results (from detector/server.py)
- Probe sessions, requests, TLS fingerprints, header captures (from probes/)

All tables live in a single database. The DB path defaults to ``data/headless.db``
and can be overridden via the ``HEADLESS_DB`` environment variable.
"""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

_DB_PATH: Path | None = None
_local = threading.local()


def _default_db_path() -> Path:
    env = os.environ.get("HEADLESS_DB")
    if env:
        return Path(env)
    return Path(__file__).parent.parent / "data" / "headless.db"


def set_db_path(path: str | Path) -> None:
    """Override the database path (call before init_db)."""
    global _DB_PATH
    _DB_PATH = Path(path)


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        db = _DB_PATH or _default_db_path()
        db.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(db), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        -- Detector verdict storage
        CREATE TABLE IF NOT EXISTS detections (
            session_id TEXT PRIMARY KEY,
            probe_data TEXT NOT NULL,
            verdict_data TEXT NOT NULL,
            overall TEXT NOT NULL,
            total_score INTEGER NOT NULL,
            client_ip TEXT,
            request_headers TEXT,
            timestamp REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_detections_overall
            ON detections(overall);
        CREATE INDEX IF NOT EXISTS idx_detections_timestamp
            ON detections(timestamp);

        -- Probe sessions
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            profile TEXT NOT NULL DEFAULT 'default',
            page TEXT NOT NULL DEFAULT '',
            created_ns INTEGER NOT NULL
        );

        -- Per-session resource requests with nanosecond timestamps
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            resource TEXT NOT NULL,
            timestamp_ns INTEGER NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );
        CREATE INDEX IF NOT EXISTS idx_requests_session
            ON requests(session_id);

        -- TLS ClientHello fingerprints (JA3/JA4)
        CREATE TABLE IF NOT EXISTS tls_fingerprints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            client_port INTEGER,
            tls_version TEXT,
            cipher_suites TEXT,
            extensions TEXT,
            supported_groups TEXT,
            ec_point_formats TEXT,
            signature_algorithms TEXT,
            alpn_protocols TEXT,
            server_name TEXT,
            ja3_hash TEXT,
            ja4_string TEXT,
            timestamp_ns INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tls_session
            ON tls_fingerprints(session_id);

        -- Wire-order HTTP header captures
        CREATE TABLE IF NOT EXISTS header_captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            resource TEXT NOT NULL,
            scheme TEXT,
            http_version TEXT,
            header_names_ordered TEXT,
            header_values TEXT,
            client_port INTEGER,
            timestamp_ns INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_header_captures_session
            ON header_captures(session_id);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Detection storage (used by detector/)
# ---------------------------------------------------------------------------

def save_detection(
    session_id: str,
    probe: dict,
    verdict: dict,
    client_ip: str | None = None,
    request_headers: dict | None = None,
) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO detections "
        "(session_id, probe_data, verdict_data, overall, total_score, "
        "client_ip, request_headers, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            json.dumps(probe),
            json.dumps(verdict),
            verdict["overall"],
            verdict["total_score"],
            client_ip,
            json.dumps(request_headers) if request_headers else None,
            time.time(),
        ),
    )
    conn.commit()


def get_detection(session_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM detections WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not row:
        return None
    return _detection_to_dict(row)


def get_all_detections(limit: int = 500) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM detections ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_detection_to_dict(r) for r in rows]


def get_stats() -> dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    headless = conn.execute(
        "SELECT COUNT(*) FROM detections WHERE overall = 'headless'"
    ).fetchone()[0]
    return {"total": total, "headless": headless, "headful": total - headless}


def _detection_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["probe"] = json.loads(d.pop("probe_data"))
    d["verdict"] = json.loads(d.pop("verdict_data"))
    if d.get("request_headers"):
        d["request_headers"] = json.loads(d["request_headers"])
    return d


# ---------------------------------------------------------------------------
# Session / request storage (used by probes/)
# ---------------------------------------------------------------------------

def create_session(
    session_id: str,
    mode: str,
    profile: str = "default",
    page: str = "",
) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO sessions "
        "(session_id, mode, profile, page, created_ns) VALUES (?, ?, ?, ?, ?)",
        (session_id, mode, profile, page, time.monotonic_ns()),
    )
    conn.commit()


def log_request(session_id: str, resource: str) -> int:
    ts = time.monotonic_ns()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO requests (session_id, resource, timestamp_ns) VALUES (?, ?, ?)",
        (session_id, resource, ts),
    )
    conn.commit()
    return ts


def get_session_requests(session_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT resource, timestamp_ns FROM requests "
        "WHERE session_id = ? ORDER BY timestamp_ns",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return dict(row) if row else None


def get_all_sessions() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT s.*, COUNT(r.id) as request_count "
        "FROM sessions s LEFT JOIN requests r ON s.session_id = r.session_id "
        "GROUP BY s.session_id ORDER BY s.created_ns DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_sessions_by_page(page: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT s.*, COUNT(r.id) as request_count "
        "FROM sessions s LEFT JOIN requests r ON s.session_id = r.session_id "
        "WHERE s.page = ? "
        "GROUP BY s.session_id ORDER BY s.created_ns",
        (page,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# TLS fingerprint storage
# ---------------------------------------------------------------------------

def log_tls_fingerprint(
    session_id: str | None,
    client_port: int,
    tls_version: str,
    cipher_suites: str,
    extensions: str,
    supported_groups: str,
    ec_point_formats: str,
    signature_algorithms: str,
    alpn_protocols: str,
    server_name: str,
    ja3_hash: str,
    ja4_string: str,
) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO tls_fingerprints "
        "(session_id, client_port, tls_version, cipher_suites, extensions, "
        "supported_groups, ec_point_formats, signature_algorithms, alpn_protocols, "
        "server_name, ja3_hash, ja4_string, timestamp_ns) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id, client_port, tls_version, cipher_suites, extensions,
            supported_groups, ec_point_formats, signature_algorithms,
            alpn_protocols, server_name, ja3_hash, ja4_string,
            time.monotonic_ns(),
        ),
    )
    conn.commit()


def get_tls_fingerprints(session_id: str | None = None) -> list[dict]:
    conn = _get_conn()
    if session_id:
        rows = conn.execute(
            "SELECT * FROM tls_fingerprints WHERE session_id = ? ORDER BY timestamp_ns",
            (session_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tls_fingerprints ORDER BY timestamp_ns"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Header capture storage
# ---------------------------------------------------------------------------

def log_header_capture(
    session_id: str,
    resource: str,
    scheme: str,
    http_version: str,
    header_names_ordered: str,
    header_values: str,
    client_port: int,
) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO header_captures "
        "(session_id, resource, scheme, http_version, header_names_ordered, "
        "header_values, client_port, timestamp_ns) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id, resource, scheme, http_version,
            header_names_ordered, header_values, client_port,
            time.monotonic_ns(),
        ),
    )
    conn.commit()


def get_header_captures(session_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM header_captures WHERE session_id = ? ORDER BY timestamp_ns",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------

def clear_all() -> None:
    """Delete all data from all tables."""
    conn = _get_conn()
    conn.executescript(
        "DELETE FROM requests; DELETE FROM sessions; "
        "DELETE FROM tls_fingerprints; DELETE FROM header_captures; "
        "DELETE FROM detections;"
    )
    conn.commit()
