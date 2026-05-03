from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone


REQUEST_CLOCK_SKEW_SECONDS = 30


def canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), canonical_json(payload), hashlib.sha256).hexdigest()


def verify_signature(payload: dict, secret: str, signature: str | None) -> bool:
    if not secret or not signature:
        return False
    expected = sign_payload(payload, secret)
    return hmac.compare_digest(expected, signature)


def validate_expires_at(expires_at: str, ttl_seconds: int, now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    try:
        normalized = expires_at.replace("Z", "+00:00")
        expires = datetime.fromisoformat(normalized)
    except ValueError:
        return "Invalid AgentForge request expiration"

    if expires.tzinfo is None:
        return "Invalid AgentForge request expiration"

    expires = expires.astimezone(timezone.utc)
    if expires.timestamp() < now.timestamp() - REQUEST_CLOCK_SKEW_SECONDS:
        return "Expired AgentForge request"

    max_expires_at = now.timestamp() + ttl_seconds + REQUEST_CLOCK_SKEW_SECONDS
    if expires.timestamp() > max_expires_at:
        return "AgentForge request expiration exceeds allowed TTL"

    return None
