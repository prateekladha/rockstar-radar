"""Symmetric encryption for broker secrets/tokens at rest (Fernet / AES).

Key from ENCRYPTION_KEY env, else a persisted local key file (0600). Never log plaintext.
"""
from __future__ import annotations
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parent.parent
_KEY_FILE = ROOT / 'data' / '.enc_key'


def _load_key() -> bytes:
    env = os.environ.get('ENCRYPTION_KEY', '').strip()
    if env:
        return env.encode()
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    try:
        _KEY_FILE.chmod(0o600)
    except OSError:
        pass
    return key


_fernet = Fernet(_load_key())


def encrypt(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet.decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
