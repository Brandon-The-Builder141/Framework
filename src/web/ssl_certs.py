"""Generate or reuse dev TLS certificates for local HTTPS (mic / secure context)."""
from __future__ import annotations

import socket
import subprocess
from pathlib import Path

from config.settings import DATA_DIR

CERT_DIR = DATA_DIR / "certs"
DEFAULT_CERT = CERT_DIR / "dev.crt"
DEFAULT_KEY = CERT_DIR / "dev.key"


def _local_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def _looks_like_ip(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def _generate_openssl(cert_path: Path, key_path: Path, hosts: list[str]) -> None:
    san_parts: list[str] = []
    for host in hosts:
        if _looks_like_ip(host):
            san_parts.append(f"IP:{host}")
        else:
            san_parts.append(f"DNS:{host}")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "825",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-addext",
            f"subjectAltName={','.join(san_parts)}",
        ],
        check=True,
        capture_output=True,
    )


def _generate_trustme(cert_path: Path, key_path: Path, hosts: list[str]) -> None:
    try:
        import trustme
    except ImportError as e:
        raise RuntimeError(
            "HTTPS needs a dev certificate. Install OpenSSL on PATH, or run: pip install trustme"
        ) from e

    ca = trustme.CA()
    server = ca.issue_cert(*hosts)
    cert_path.write_bytes(b"".join(pem.bytes() for pem in server.cert_chain_pems))
    key_path.write_bytes(server.private_key_pem.bytes())


def ensure_dev_certs(
    cert_path: Path | None = None,
    key_path: Path | None = None,
    *,
    regen: bool = False,
) -> tuple[Path, Path]:
    """Return (cert, key) paths, creating a self-signed pair if missing."""
    cert_path = cert_path or DEFAULT_CERT
    key_path = key_path or DEFAULT_KEY
    if cert_path.exists() and key_path.exists() and not regen:
        return cert_path, key_path

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    hosts = ["localhost", "127.0.0.1"]
    ip = _local_ip()
    if ip and ip not in hosts:
        hosts.append(ip)

    if cert_path.exists():
        cert_path.unlink()
    if key_path.exists():
        key_path.unlink()

    try:
        _generate_openssl(cert_path, key_path, hosts)
    except (FileNotFoundError, subprocess.CalledProcessError):
        _generate_trustme(cert_path, key_path, hosts)

    return cert_path, key_path
