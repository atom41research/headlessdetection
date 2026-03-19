"""TLS ClientHello parser and JA3/JA4 fingerprint computation.

Uses ssl._msg_callback to intercept raw TLS records during handshake.
Parses the ClientHello to extract cipher suites, extensions, and other
fields needed for JA3/JA4 fingerprinting.
"""

import hashlib
import struct
import threading
from dataclasses import dataclass, field


@dataclass
class ClientHelloInfo:
    tls_version: int = 0
    cipher_suites: list[int] = field(default_factory=list)
    extensions: list[int] = field(default_factory=list)
    supported_groups: list[int] = field(default_factory=list)
    ec_point_formats: list[int] = field(default_factory=list)
    signature_algorithms: list[int] = field(default_factory=list)
    alpn_protocols: list[str] = field(default_factory=list)
    server_name: str = ""


# GREASE values to filter out (RFC 8701)
GREASE_VALUES = {
    0x0A0A, 0x1A1A, 0x2A2A, 0x3A3A, 0x4A4A, 0x5A5A, 0x6A6A, 0x7A7A,
    0x8A8A, 0x9A9A, 0xAAAA, 0xBABA, 0xCACA, 0xDADA, 0xEAEA, 0xFAFA,
}


def _is_grease(value: int) -> bool:
    return value in GREASE_VALUES


def parse_client_hello(data: bytes) -> ClientHelloInfo:
    """Parse a TLS ClientHello message from raw bytes.

    The data should be the Handshake message body (after the 5-byte record header
    and 4-byte handshake header), or the full handshake message starting with
    the handshake type byte.
    """
    info = ClientHelloInfo()
    offset = 0

    # If data starts with handshake type (0x01 = ClientHello), skip handshake header
    if len(data) > 4 and data[0] == 0x01:
        # Handshake type (1) + length (3)
        offset = 4

    if len(data) < offset + 38:
        return info

    # ClientHello fields:
    # ProtocolVersion (2 bytes)
    info.tls_version = struct.unpack_from("!H", data, offset)[0]
    offset += 2

    # Random (32 bytes)
    offset += 32

    # Session ID (1 byte length + variable)
    if offset >= len(data):
        return info
    session_id_len = data[offset]
    offset += 1 + session_id_len

    # Cipher Suites (2 byte length + variable, 2 bytes each)
    if offset + 2 > len(data):
        return info
    cs_len = struct.unpack_from("!H", data, offset)[0]
    offset += 2
    for i in range(0, cs_len, 2):
        if offset + 2 > len(data):
            break
        cs = struct.unpack_from("!H", data, offset)[0]
        info.cipher_suites.append(cs)
        offset += 2

    # Compression Methods (1 byte length + variable)
    if offset >= len(data):
        return info
    comp_len = data[offset]
    offset += 1 + comp_len

    # Extensions (2 byte total length + variable)
    if offset + 2 > len(data):
        return info
    ext_total_len = struct.unpack_from("!H", data, offset)[0]
    offset += 2
    ext_end = offset + ext_total_len

    while offset + 4 <= ext_end and offset + 4 <= len(data):
        ext_type = struct.unpack_from("!H", data, offset)[0]
        ext_len = struct.unpack_from("!H", data, offset + 2)[0]
        offset += 4
        ext_data = data[offset:offset + ext_len]

        info.extensions.append(ext_type)

        # Parse specific extensions
        if ext_type == 0x0000:  # server_name
            info.server_name = _parse_sni(ext_data)
        elif ext_type == 0x000A:  # supported_groups (elliptic_curves)
            info.supported_groups = _parse_u16_list(ext_data)
        elif ext_type == 0x000B:  # ec_point_formats
            info.ec_point_formats = _parse_u8_list(ext_data)
        elif ext_type == 0x000D:  # signature_algorithms
            info.signature_algorithms = _parse_u16_list(ext_data)
        elif ext_type == 0x0010:  # ALPN
            info.alpn_protocols = _parse_alpn(ext_data)

        offset += ext_len

    return info


def _parse_sni(data: bytes) -> str:
    """Parse Server Name Indication extension data."""
    if len(data) < 5:
        return ""
    # SNI list length (2) + type (1) + name length (2) + name
    name_len = struct.unpack_from("!H", data, 3)[0]
    if len(data) < 5 + name_len:
        return ""
    return data[5:5 + name_len].decode("ascii", errors="replace")


def _parse_u16_list(data: bytes) -> list[int]:
    """Parse a length-prefixed list of uint16 values."""
    if len(data) < 2:
        return []
    list_len = struct.unpack_from("!H", data, 0)[0]
    result = []
    for i in range(2, min(2 + list_len, len(data)), 2):
        if i + 2 <= len(data):
            result.append(struct.unpack_from("!H", data, i)[0])
    return result


def _parse_u8_list(data: bytes) -> list[int]:
    """Parse a length-prefixed list of uint8 values."""
    if len(data) < 1:
        return []
    list_len = data[0]
    return list(data[1:1 + list_len])


def _parse_alpn(data: bytes) -> list[str]:
    """Parse ALPN extension data."""
    if len(data) < 2:
        return []
    total_len = struct.unpack_from("!H", data, 0)[0]
    result = []
    offset = 2
    end = min(2 + total_len, len(data))
    while offset < end:
        proto_len = data[offset]
        offset += 1
        if offset + proto_len <= end:
            result.append(data[offset:offset + proto_len].decode("ascii", errors="replace"))
        offset += proto_len
    return result


def compute_ja3(info: ClientHelloInfo) -> str:
    """Compute JA3 fingerprint hash.

    Format: TLSVersion,Ciphers,Extensions,EllipticCurves,EllipticCurvePointFormats
    Each list is dash-separated. GREASE values are filtered out.
    """
    version = str(info.tls_version)
    ciphers = "-".join(str(c) for c in info.cipher_suites if not _is_grease(c))
    extensions = "-".join(str(e) for e in info.extensions if not _is_grease(e))
    curves = "-".join(str(g) for g in info.supported_groups if not _is_grease(g))
    points = "-".join(str(p) for p in info.ec_point_formats)

    ja3_str = ",".join([version, ciphers, extensions, curves, points])
    ja3_hash = hashlib.md5(ja3_str.encode()).hexdigest()
    return ja3_hash


def compute_ja3_raw(info: ClientHelloInfo) -> str:
    """Return the raw JA3 string (before hashing) for inspection."""
    version = str(info.tls_version)
    ciphers = "-".join(str(c) for c in info.cipher_suites if not _is_grease(c))
    extensions = "-".join(str(e) for e in info.extensions if not _is_grease(e))
    curves = "-".join(str(g) for g in info.supported_groups if not _is_grease(g))
    points = "-".join(str(p) for p in info.ec_point_formats)
    return ",".join([version, ciphers, extensions, curves, points])


def compute_ja4(info: ClientHelloInfo) -> str:
    """Compute JA4 fingerprint string.

    Format: t{version_char}{sni_flag}{cipher_count}{ext_count}_{sorted_cipher_hash}_{sorted_ext_hash}

    Simplified JA4 — full JA4 has more complexity but this captures the key signals.
    """
    # Version character
    ver_map = {0x0301: "10", 0x0302: "11", 0x0303: "12", 0x0304: "13"}
    ver_str = ver_map.get(info.tls_version, "00")

    # SNI flag
    sni_flag = "d" if info.server_name else "i"

    # Filter GREASE
    ciphers = [c for c in info.cipher_suites if not _is_grease(c)]
    exts = [e for e in info.extensions if not _is_grease(e)]

    # Counts (zero-padded to 2 digits)
    cipher_count = f"{min(len(ciphers), 99):02d}"
    ext_count = f"{min(len(exts), 99):02d}"

    # Sorted cipher hash (first 12 chars of sha256 of sorted comma-separated values)
    sorted_ciphers = ",".join(str(c) for c in sorted(ciphers))
    cipher_hash = hashlib.sha256(sorted_ciphers.encode()).hexdigest()[:12]

    # Sorted extension hash
    sorted_exts = ",".join(str(e) for e in sorted(exts))
    ext_hash = hashlib.sha256(sorted_exts.encode()).hexdigest()[:12]

    # Protocol (t=TCP, q=QUIC)
    return f"t{ver_str}{sni_flag}{cipher_count}{ext_count}_{cipher_hash}_{ext_hash}"


# --- Global fingerprint store and callback ---

_lock = threading.Lock()
# Maps id(ssl_object) -> ClientHelloInfo
fingerprint_store: dict[int, ClientHelloInfo] = {}


def tls_msg_callback(conn, direction, version, content_type, msg_type, data):
    """OpenSSL message callback for intercepting TLS records.

    Set via ssl.SSLContext._msg_callback to capture ClientHello messages.

    Args:
        conn: SSLObject
        direction: "read" or "write"
        version: TLS version from record layer
        content_type: TLS content type (22 = Handshake)
        msg_type: Handshake message type (1 = ClientHello)
        data: Raw message bytes
    """
    # We want ClientHello: direction=read, content_type=22 (Handshake), msg_type=1 (ClientHello)
    if direction == "read" and content_type == 22 and msg_type == 1:
        try:
            info = parse_client_hello(data)
            with _lock:
                fingerprint_store[id(conn)] = info
        except Exception:
            pass  # Don't break TLS handshake on parse errors


def get_fingerprint_by_conn_id(conn_id: int) -> ClientHelloInfo | None:
    """Retrieve a stored fingerprint by ssl object id."""
    with _lock:
        return fingerprint_store.get(conn_id)


def clear_store():
    """Clear all stored fingerprints."""
    with _lock:
        fingerprint_store.clear()
