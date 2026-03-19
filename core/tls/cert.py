"""Self-signed certificate generation and cert path resolution."""

import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import ipaddress


def generate_self_signed_cert(output_dir: Path) -> tuple[Path, Path]:
    """Generate a self-signed cert for localhost/127.0.0.1.

    Returns (cert_path, key_path). Reuses existing certs if present.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cert_path = output_dir / "localhost.pem"
    key_path = output_dir / "localhost-key.pem"

    if cert_path.exists() and key_path.exists():
        # Check if cert is still valid
        cert_data = cert_path.read_bytes()
        cert = x509.load_pem_x509_certificate(cert_data)
        if cert.not_valid_after_utc > datetime.datetime.now(datetime.timezone.utc):
            return cert_path, key_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path


def get_cert_paths(
    cert_file: Path | None = None,
    key_file: Path | None = None,
    auto_generate_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Resolve certificate paths.

    If cert_file/key_file are provided (e.g. real Let's Encrypt certs), use those.
    Otherwise generate self-signed certs in auto_generate_dir.
    """
    if cert_file and key_file:
        if not cert_file.exists():
            raise FileNotFoundError(f"Certificate file not found: {cert_file}")
        if not key_file.exists():
            raise FileNotFoundError(f"Key file not found: {key_file}")
        return cert_file, key_file

    if auto_generate_dir is None:
        auto_generate_dir = Path(__file__).parent.parent.parent / "data" / "certs"

    return generate_self_signed_cert(auto_generate_dir)
