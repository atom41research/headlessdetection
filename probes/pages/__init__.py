"""Page helpers."""
from pathlib import Path

_BEACON_PATH = Path(__file__).parent.parent / "static" / "beacon.png"
_BEACON_BYTES_CACHE = None


def _beacon_bytes() -> bytes:
    global _BEACON_BYTES_CACHE
    if _BEACON_BYTES_CACHE is None:
        _BEACON_BYTES_CACHE = _BEACON_PATH.read_bytes()
    return _BEACON_BYTES_CACHE


def _log_track(session_id: str, resource: str):
    from core import storage
    storage.log_request(session_id, resource)
