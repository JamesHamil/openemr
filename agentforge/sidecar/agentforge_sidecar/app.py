from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request

from .observability import flush_langfuse
from .schemas import AgentForgeRequest, AgentForgeResponse
from .security import verify_signature
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
    if not verify_signature(body, settings.signing_secret, x_agentforge_signature):
        raise HTTPException(status_code=401, detail="Invalid AgentForge request signature")

    agent_request = AgentForgeRequest.model_validate(body)
    response, trace = handle_chat(agent_request, settings)
    print(trace.model_dump_json())
    flush_langfuse(settings)
    return response
