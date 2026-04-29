from __future__ import annotations

import time
import uuid

from .mock_provider import mock_response
from .openai_provider import openai_response
from .schemas import AgentForgeRequest, AgentForgeResponse, TraceRecord, WarningItem
from .settings import Settings
from .verifier import verify_response


def handle_chat(request: AgentForgeRequest, settings: Settings) -> tuple[AgentForgeResponse, TraceRecord]:
    started = time.perf_counter()
    trace_id = f"af-{uuid.uuid4()}"
    error = ""

    try:
        if settings.mode == "off":
            response = AgentForgeResponse(
                answer="Clinical Co-Pilot is currently disabled.",
                sections=[],
                claims=[],
                sources=[],
                warnings=[
                    WarningItem(
                        code="agentforge_off",
                        message="The sidecar is configured in off mode.",
                    )
                ],
                blocked_claims=[],
                verification_status="failed",
                trace_id=trace_id,
            )
        elif settings.mode == "real":
            response = openai_response(request, trace_id, settings.model)
        else:
            response = mock_response(request, trace_id)

        if response.verification_status not in {"refused", "failed"}:
            response = verify_response(request, response)
    except Exception as exc:
        error = str(exc)
        response = AgentForgeResponse(
            answer="Clinical Co-Pilot could not produce a verified response.",
            sections=[],
            claims=[],
            sources=[],
            warnings=[WarningItem(code="sidecar_exception", message="The sidecar returned a controlled failure.")],
            blocked_claims=[],
            verification_status="failed",
            trace_id=trace_id,
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    trace = TraceRecord(
        trace_id=trace_id,
        request_id=request.request_id,
        conversation_id=request.conversation_id,
        mode=settings.mode,
        verification_status=response.verification_status,
        source_count=len(request.evidence_bundle.sources),
        collector_statuses=request.evidence_bundle.adapter_status,
        blocked_claim_count=len(response.blocked_claims),
        estimated_input_tokens=_rough_tokens(request.model_dump_json()),
        estimated_output_tokens=_rough_tokens(response.model_dump_json()),
        estimated_cost_usd=0.0,
        latency_ms=latency_ms,
        error=error,
    )
    return response, trace


def _rough_tokens(text: str) -> int:
    return max(1, len(text) // 4)
