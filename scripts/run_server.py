"""Dual HTTP + HTTPS server launcher with TLS fingerprint capture.

Usage:
    uv run python scripts/run_server.py
    uv run python scripts/run_server.py --cert-file /path/to/cert.pem --key-file /path/to/key.pem
    uv run python scripts/run_server.py --https-port 8443 --http-port 8000
"""

import argparse
import asyncio
import sys
from pathlib import Path

import uvicorn

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.tls.cert import get_cert_paths
from core.tls.fingerprint import tls_msg_callback


async def run_servers(args: argparse.Namespace):
    cert_file_arg = Path(args.cert_file) if args.cert_file else None
    key_file_arg = Path(args.key_file) if args.key_file else None

    cert_path, key_path = get_cert_paths(
        cert_file=cert_file_arg,
        key_file=key_file_arg,
    )
    print(f"Using certificate: {cert_path}")
    print(f"Using key: {key_path}")

    http_config = uvicorn.Config(
        "probes.server:app",
        host="0.0.0.0",
        port=args.http_port,
        log_level="info",
    )
    https_config = uvicorn.Config(
        "probes.server:app",
        host="0.0.0.0",
        port=args.https_port,
        log_level="info",
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
    )

    # Patch the SSLContext after Config creates it so we can attach _msg_callback
    https_config.load()
    if https_config.ssl:
        https_config.ssl._msg_callback = tls_msg_callback
        print("Patched SSLContext with _msg_callback for TLS capture")

    http_server = uvicorn.Server(http_config)
    https_server = uvicorn.Server(https_config)

    print(f"\nStarting HTTP  server on http://127.0.0.1:{args.http_port}")
    print(f"Starting HTTPS server on https://127.0.0.1:{args.https_port}")
    print(f"TLS ClientHello capture: ENABLED via ssl._msg_callback")
    print(f"Header order capture: ENABLED via HeaderCaptureMiddleware\n")

    await asyncio.gather(
        http_server.serve(),
        https_server.serve(),
    )


def main():
    parser = argparse.ArgumentParser(description="HTTP + HTTPS server with TLS fingerprinting")
    parser.add_argument("--http-port", type=int, default=8000, help="HTTP port (default: 8000)")
    parser.add_argument("--https-port", type=int, default=8443, help="HTTPS port (default: 8443)")
    parser.add_argument("--cert-file", type=str, default=None, help="Path to TLS certificate (PEM)")
    parser.add_argument("--key-file", type=str, default=None, help="Path to TLS private key (PEM)")
    args = parser.parse_args()

    asyncio.run(run_servers(args))


if __name__ == "__main__":
    main()
