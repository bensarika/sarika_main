"""Provider API keys at rest.

Keys entered in Admin › Models are stored as Fernet tokens. The Fernet key is
derived from ``PS_SECRET_KEY`` (production must set a strong one), so rotating
the secret invalidates stored keys — admins re-enter them, nothing leaks.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from protocol_studio.settings import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(("provider-keys:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError("stored provider key cannot be decrypted (PS_SECRET_KEY changed?) — re-enter it") from e


def hint(plain: str) -> str:
    return plain[-4:] if len(plain) >= 8 else ""
