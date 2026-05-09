from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mode: str = "real"
    model: str = "gpt-5-nano"
    compose_model: str = ""
    verify_model: str = ""
    reasoning_effort: str = "low"
    signing_secret: str = ""
    openai_api_key: str = ""
    request_ttl_seconds: int = 300
    source_selection_mode: str = "auto"
    verify_mode: str = "auto"
    fast_model_provider: str = "none"
    response_cache_enabled: bool = False
    response_cache_ttl_seconds: int = 120
    langfuse_enabled: bool = False
    langfuse_capture_payloads: bool = False
    langfuse_flush_at_end: bool = False
    langfuse_environment: str = "local"
    langfuse_tags: tuple[str, ...] = ()

    @property
    def reasoning(self) -> dict[str, str]:
        return {"effort": self.reasoning_effort}


def load_settings() -> Settings:
    mode = os.getenv("AGENTFORGE_MODE", "real").strip().lower()
    if mode not in {"real", "mock", "off"}:
        mode = "real"

    reasoning_effort = os.getenv("AGENTFORGE_REASONING_EFFORT", "low").strip().lower()
    if reasoning_effort not in {"minimal", "low", "medium", "high", "xhigh"}:
        reasoning_effort = "low"

    source_selection_mode = os.getenv("AGENTFORGE_SOURCE_SELECTION_MODE", "auto").strip().lower()
    if source_selection_mode not in {"auto", "deterministic", "model"}:
        source_selection_mode = "auto"

    verify_mode = os.getenv("AGENTFORGE_VERIFY_MODE", "auto").strip().lower()
    if verify_mode not in {"auto", "deterministic", "model"}:
        verify_mode = "auto"

    fast_model_provider = os.getenv("AGENTFORGE_FAST_MODEL_PROVIDER", "none").strip().lower()
    if fast_model_provider not in {"none", "openai", "external"}:
        fast_model_provider = "none"

    ttl_raw = os.getenv("AGENTFORGE_REQUEST_TTL_SECONDS", "300")
    try:
        ttl = max(30, int(ttl_raw))
    except ValueError:
        ttl = 300

    cache_ttl_raw = os.getenv("AGENTFORGE_RESPONSE_CACHE_TTL_SECONDS", "120")
    try:
        cache_ttl = max(15, int(cache_ttl_raw))
    except ValueError:
        cache_ttl = 120

    return Settings(
        mode=mode,
        model=os.getenv("AGENTFORGE_OPENAI_MODEL", "gpt-5-nano"),
        compose_model=os.getenv("AGENTFORGE_COMPOSE_MODEL", ""),
        verify_model=os.getenv("AGENTFORGE_VERIFY_MODEL", ""),
        reasoning_effort=reasoning_effort,
        signing_secret=os.getenv("AGENTFORGE_SIGNING_SECRET", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        request_ttl_seconds=ttl,
        source_selection_mode=source_selection_mode,
        verify_mode=verify_mode,
        fast_model_provider=fast_model_provider,
        response_cache_enabled=_env_bool("AGENTFORGE_RESPONSE_CACHE_ENABLED", False),
        response_cache_ttl_seconds=cache_ttl,
        langfuse_enabled=_env_bool("AGENTFORGE_LANGFUSE_ENABLED", False),
        langfuse_capture_payloads=_env_bool("AGENTFORGE_LANGFUSE_CAPTURE_PAYLOADS", False),
        langfuse_flush_at_end=_env_bool("AGENTFORGE_LANGFUSE_FLUSH_AT_END", False),
        langfuse_environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT", os.getenv("AGENTFORGE_ENVIRONMENT", "local")),
        langfuse_tags=_csv_tuple(os.getenv("AGENTFORGE_LANGFUSE_TAGS", "")),
    )
  

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv_tuple(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())
