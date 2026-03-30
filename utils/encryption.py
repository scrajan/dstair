"""
Symmetric encryption utilities for at-rest secret storage.
Uses Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from the app SECRET_KEY.

Important: If SECRET_KEY changes, previously encrypted values will be unreadable.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# ── Lazy-initialised cipher ────────────────────────────────────
# The Fernet instance is created once on first call, then cached.
_fernet_instance = None


def _get_fernet():
    """Return a cached Fernet cipher derived from the app's SECRET_KEY."""
    global _fernet_instance
    if _fernet_instance is None:
        from flask import current_app
        secret = current_app.config['SECRET_KEY']
        # Derive a URL-safe 32-byte key from SECRET_KEY using SHA-256
        derived = hashlib.sha256(secret.encode()).digest()
        key = base64.urlsafe_b64encode(derived)
        _fernet_instance = Fernet(key)
    return _fernet_instance


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string, returning a Fernet token string."""
    if not plaintext:
        return plaintext
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """
    Decrypt a Fernet token string back to plaintext.
    If the value isn't a valid Fernet token (e.g., legacy plaintext),
    return it as-is for backward compatibility.
    """
    if not ciphertext:
        return ciphertext
    fernet = _get_fernet()
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        # Value is likely legacy plaintext — return as-is
        logger.debug("Decryption failed — treating value as legacy plaintext.")
        return ciphertext


def is_encrypted(value: str) -> bool:
    """Check if a value looks like a Fernet token (starts with 'gAAAAA')."""
    return bool(value) and value.startswith('gAAAAA')
