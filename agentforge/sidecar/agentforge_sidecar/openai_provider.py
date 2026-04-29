from __future__ import annotations

import json

from .mock_provider import mock_response
from .schemas import AgentForgeRequest, AgentForgeResponse


SYSTEM_PROMPT = """You are AgentForge Clinical Co-Pilot for a hospitalist preparing for rounds.
Use only the provided evidence bundle. Do not provide treatment directives. Every factual
clinical claim must cite source_ids that support it. If evidence is missing, say it was not
found in retrieved records rather than absent from reality."""


def openai_response(request: AgentForgeRequest, trace_id: str, model: str) -> AgentForgeResponse:
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - depends on runtime dependency
        failed = mock_response(request, trace_id)
        return failed.model_copy(
            update={
                "answer": f"OpenAI real mode is not available in this runtime: {exc}",
                "claims": [],
                "sources": [],
                "warnings": [],
                "blocked_claims": [],
                "verification_status": "failed",
            }
        )

    client = OpenAI()
    payload = request.model_dump()
    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Return a JSON response matching the AgentForgeResponse schema for this request:\n"
                + json.dumps(payload, separators=(",", ":")),
            },
        ],
        text_format=AgentForgeResponse,
    )
    parsed = response.output_parsed
    if not parsed:
        raise RuntimeError("OpenAI response did not include parsed AgentForgeResponse output")
    return parsed.model_copy(update={"trace_id": trace_id})
