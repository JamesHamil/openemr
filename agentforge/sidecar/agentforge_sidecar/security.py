from __future__ import annotations

import hashlib
import hmac
import json


def canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), canonical_json(payload), hashlib.sha256).hexdigest()


def verify_signature(payload: dict, secret: str, signature: str | None) -> bool:
    if not signature:
        return False
    expected = sign_payload(payload, secret)
    return hmac.compare_digest(expected, signature)
