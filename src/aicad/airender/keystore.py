"""Encryption at rest for workspace API keys (BYO OpenAI key).

The key is encrypted with Fernet (AES-128-CBC + HMAC-SHA256). The Fernet key is derived (SHA-256) from the server
secret `FW_SECRET_KEY`; in development, when it is not set, a random secret is generated once into
`<data_dir>/secret.key` (data/ is never committed). Production refuses to run without `FW_SECRET_KEY`, so keys
can't end up encrypted with a throwaway secret.

Plain keys never leave this module except to the provider call: API responses carry only `mask()`ed hints, and
nothing here logs.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from aicad.platform.config import get_settings

PREFIX = "v1:"
_KEY_RE = re.compile(r"^sk-[A-Za-z0-9_\-]{16,300}$")


class KeyStoreError(RuntimeError):
    pass


def _secret() -> bytes:
    env = os.environ.get("FW_SECRET_KEY", "").strip()
    if env:
        return env.encode()
    s = get_settings()
    if s.production:
        raise KeyStoreError("FW_SECRET_KEY must be set in production to store API keys.")
    f: Path = s.data_dir / "secret.key"
    if not f.is_file():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        try:
            f.chmod(0o600)
        except OSError:
            pass
    return f.read_text(encoding="utf-8").strip().encode()


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"formwright-keystore:" + _secret()).digest()))


def encrypt(plain: str) -> str:
    return PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    if not token.startswith(PREFIX):
        raise KeyStoreError("Unknown key format")
    try:
        return _fernet().decrypt(token[len(PREFIX):].encode()).decode()
    except InvalidToken as e:
        raise KeyStoreError("The stored key can't be decrypted (the server secret changed). Add the key again.") \
            from e


def looks_like_key(key: str) -> bool:
    return bool(_KEY_RE.fullmatch(key or ""))


def mask(key: str) -> str:
    """`sk-…AbCd`: enough to recognise a key, never enough to use it."""
    return f"sk-…{key[-4:]}" if len(key) >= 12 else "sk-…"


def scrub(text: str) -> str:
    """Remove anything that looks like an API key from a message before it is stored or shown."""
    return re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "sk-…", text or "")
