"""
Credential encryption utilities.

All exchange credentials are encrypted with Fernet symmetric encryption before
being written to the local SQLite database. The encryption key is derived
deterministically from the machine ID so the database cannot be decrypted on a
different machine.
"""

import base64
import hashlib
import logging
import platform
import subprocess
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Fixed application salt for PBKDF2 domain separation (not secret).
_SALT = b"crypto-cli-v1"
_PBKDF2_ITERATIONS = 100_000


def get_machine_id() -> str:
    """
    Return a stable, machine-unique identifier string.

    Resolution order:
      1. /etc/machine-id  (Linux systemd)
      2. IOPlatformUUID via ioreg  (macOS)
      3. platform.node() fallback  (hostname — less unique but always available)
    """
    # Linux
    mid_path = Path("/etc/machine-id")
    if mid_path.exists():
        value = mid_path.read_text().strip()
        if value:
            return value

    # macOS
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True,
            timeout=5,
        )
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                # Line format: "IOPlatformUUID" = "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
                parts = line.split('"')
                if len(parts) >= 4:
                    return parts[-2]
    except Exception:
        pass

    # Fallback: hostname
    return platform.node()


def derive_key(machine_id: str) -> bytes:
    """
    Derive a 32-byte Fernet-compatible key from *machine_id* using
    PBKDF2-HMAC-SHA256 with a fixed application salt.

    Returns URL-safe base64-encoded bytes suitable for ``Fernet(key)``.
    """
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        machine_id.encode(),
        _SALT,
        iterations=_PBKDF2_ITERATIONS,
        dklen=32,
    )
    return base64.urlsafe_b64encode(raw)


def get_fernet() -> Fernet:
    """Return a Fernet instance keyed to the current machine."""
    key = derive_key(get_machine_id())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """
    Encrypt *plaintext* and return a URL-safe base64 ciphertext string.

    The result is safe to store in SQLite TEXT columns.
    """
    return get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """
    Decrypt a ciphertext string produced by :func:`encrypt` and return the
    original plaintext.

    Raises ``cryptography.fernet.InvalidToken`` if the ciphertext is invalid
    or was encrypted on a different machine.
    """
    return get_fernet().decrypt(ciphertext.encode()).decode()
