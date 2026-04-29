from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mode: str = "mock"
    model: str = "gpt-4.1-mini"
    signing_secret: str = "dev-agentforge-signing-secret"
    openai_api_key: str = ""
    request_ttl_seconds: int = 300


def load_settings() -> Settings:
    mode = os.getenv("AGENTFORGE_MODE", "mock").strip().lower()
    if mode not in {"real", "mock", "off"}:
        mode = "mock"

    ttl_raw = os.getenv("AGENTFORGE_REQUEST_TTL_SECONDS", "300")
    try:
        ttl = max(30, int(ttl_raw))
    except ValueError:
        ttl = 300

    return Settings(
        mode=mode,
        model=os.getenv("AGENTFORGE_OPENAI_MODEL", "gpt-4.1-mini"),
        signing_secret=os.getenv("AGENTFORGE_SIGNING_SECRET", "dev-agentforge-signing-secret"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        request_ttl_seconds=ttl,
    )
