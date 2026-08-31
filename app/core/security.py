"""
Fernet encrypt/decrypt for the session blob at rest, and constant-time
admin token comparison.
"""

import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def encrypt(plaintext: bytes) -> bytes:
    f = Fernet(settings.fernet_key.encode())
    return f.encrypt(plaintext)


def decrypt(ciphertext: bytes) -> bytes:
    """Raises cryptography.fernet.InvalidToken if ciphertext is corrupt,
    was encrypted with a different key, or has been tampered with. Callers
    should treat this as "no valid session," not a crash — see
    SessionManager.load()."""
    f = Fernet(settings.fernet_key.encode())
    return f.decrypt(ciphertext)


def is_valid_admin_token(candidate: str) -> bool:
    """hmac.compare_digest instead of `==` to avoid a timing side-channel:
    `==` short-circuits on the first mismatched character, leaking how many
    leading characters were correct via response time."""
    return hmac.compare_digest(candidate.encode(), settings.admin_token.encode())


__all__ = ["encrypt", "decrypt", "InvalidToken", "is_valid_admin_token"]
