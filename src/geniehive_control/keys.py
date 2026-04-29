from __future__ import annotations

import hashlib
import hmac
import secrets


DEFAULT_KEY_PREFIX = "gh"


def generate_api_key(*, prefix: str = DEFAULT_KEY_PREFIX, token_bytes: int = 32) -> str:
    """Generate a URL-safe API key. The raw value is only shown once."""
    token = secrets.token_urlsafe(token_bytes)
    return f"{prefix}_{token}"


def hash_api_key(api_key: str, *, secret: str) -> str:
    if not secret:
        raise ValueError("key hash secret must not be empty")
    digest = hmac.new(
        secret.encode("utf-8"),
        api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest}"


def verify_api_key(api_key: str, key_hash: str, *, secret: str) -> bool:
    try:
        expected = hash_api_key(api_key, secret=secret)
    except ValueError:
        return False
    return hmac.compare_digest(expected, key_hash)


def redact_api_key(api_key: str) -> str:
    if len(api_key) <= 12:
        return "***"
    return f"{api_key[:6]}...{api_key[-4:]}"
