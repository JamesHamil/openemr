from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request

from .observability import flush_langfuse
from .schemas import AgentForgeRequest, AgentForgeResponse
from .security import validate_expires_at, verify_signature
from .service import handle_chat
from .settings import load_settings

app = FastAPI(title="AgentForge Clinical Co-Pilot Sidecar", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    settings = load_settings()
    return {"status": "ok", "mode": settings.mode, "service": "agentforge-sidecar"}


@app.post("/v1/chat", response_model=AgentForgeResponse)
async def chat(
    request: Request,
    x_agentforge_signature: str | None = Header(default=None),
) -> AgentForgeResponse:
    settings = load_settings()
    body = await request.json()
    if not settings.signing_secret:
        raise HTTPException(status_code=503, detail="AgentForge signing secret is not configured")
    if not verify_signature(body, settings.signing_secret, x_agentforge_signature):
        raise HTTPException(status_code=401, detail="Invalid AgentForge request signature")

    agent_request = AgentForgeRequest.model_validate(body)
    expiration_error = validate_expires_at(agent_request.expires_at, settings.request_ttl_seconds)
    if expiration_error:
        raise HTTPException(status_code=401, detail=expiration_error)

    response, trace = handle_chat(agent_request, settings)
    print(trace.model_dump_json())
    flush_langfuse(settings)
    return response
