"""ASGI middleware that captures ordered HTTP headers on every request.

Headers arrive from the HTTP parser (h11/httptools) in wire order.
Starlette preserves this order in scope["headers"] as list[tuple[bytes, bytes]].
"""

import json
import time
import threading
from urllib.parse import parse_qs

from core import storage

# In-memory store: session_id -> list of captures
_lock = threading.Lock()
_captures: dict[str, list[dict]] = {}


def _extract_session_id(scope: dict) -> str | None:
    """Extract session ID from query string (?s=...)."""
    qs = scope.get("query_string", b"").decode("latin-1")
    params = parse_qs(qs)
    s_values = params.get("s")
    return s_values[0] if s_values else None


class HeaderCaptureMiddleware:
    """ASGI middleware that logs ordered headers for every request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            session_id = _extract_session_id(scope)
            if session_id:
                raw_headers = scope.get("headers", [])
                client = scope.get("client", (None, None))
                scheme = scope.get("scheme", "http")
                http_version = scope.get("http_version", "1.1")
                path = scope.get("path", "")

                header_names = [name.decode("latin-1") for name, _ in raw_headers]
                header_values = {
                    name.decode("latin-1"): value.decode("latin-1")
                    for name, value in raw_headers
                }

                capture = {
                    "path": path,
                    "scheme": scheme,
                    "http_version": http_version,
                    "client_ip": client[0],
                    "client_port": client[1],
                    "header_names_ordered": header_names,
                    "header_values": header_values,
                    "timestamp_ns": time.monotonic_ns(),
                }

                with _lock:
                    _captures.setdefault(session_id, []).append(capture)

                # Persist to DB for cross-process analysis
                try:
                    storage.log_header_capture(
                        session_id=session_id,
                        resource=path,
                        scheme=scheme,
                        http_version=http_version,
                        header_names_ordered=json.dumps(header_names),
                        header_values=json.dumps(header_values),
                        client_port=client[1] or 0,
                    )
                except Exception:
                    pass  # Don't break requests on DB errors

        await self.app(scope, receive, send)


def get_captures(session_id: str) -> list[dict]:
    """Return all header captures for a session."""
    with _lock:
        return list(_captures.get(session_id, []))


def get_all_session_ids() -> list[str]:
    """Return all session IDs that have captures."""
    with _lock:
        return list(_captures.keys())


def clear_captures():
    """Clear all stored captures."""
    with _lock:
        _captures.clear()
