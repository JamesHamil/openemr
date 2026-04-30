from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .schemas import AgentForgeRequest, AgentForgeResponse, WarningItem
from .tool_agent import ToolPhaseDiagnostics, run_tool_phase


COMPOSE_PROMPT = """You are AgentForge Clinical Co-Pilot for a hospitalist preparing for rounds.
Use only the selected evidence provided in this request payload. Never provide treatment directives,
orders, diagnoses, or medication changes. Every factual clinical claim must cite source_ids from selected evidence.

Choose the output shape that best fits the user request:
- Chart brief: one-liner, active chart issues, meds/allergies, recent objective data,
  missing data, and questions/issues for physician review.
- Follow-up question: direct answer first, then supporting evidence and missing-data notes.
- Treatment/action request: refuse the directive and offer to summarize record-backed issues.

Keep the answer concise and physician-natural: <=180 words, <=8 claims, <=10 displayed sources.
Start answer with a direct natural-language response to the specific question.
Avoid unrelated chart inventory unless directly needed for the question.
If evidence is limited, include one short clinician guidance sentence about what to confirm in chart.
Use compact inline citations only when useful (for example [problem-12]).
For narrow follow-up questions, sections may be empty and claims may be minimal.
For broad chart-summary requests, include sections with scannable claims.
Use answer for the top-line response and claims/sections for supporting details.
Return only sources that are cited by claims. Keep each extracted_value short.
Say evidence was not found in retrieved records rather than absent from reality."""


@dataclass(frozen=True)
class ProviderDiagnostics:
    tool_call_count: int = 0
    selected_source_count: int = 0
    fallback_reason: str = ""
    planning_latency_ms: int = 0
    compose_latency_ms: int = 0


def openai_response(request: AgentForgeRequest, trace_id: str, model: str) -> tuple[AgentForgeResponse, ProviderDiagnostics]:
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - depends on runtime dependency
        return _provider_partial_fallback(
            request=request,
            trace_id=trace_id,
            warning_code="openai_runtime_unavailable",
            warning_message=f"OpenAI real mode is not available in this runtime: {exc}",
            fallback_reason="openai_runtime_unavailable",
        )
    try:
        client = OpenAI()
        tool_plan, tool_diag = run_tool_phase(client, request, model)
        selected_sources = _selected_sources(request, tool_plan.selected_source_ids)
        if not selected_sources:
            warnings = []
            reason = tool_diag.fallback_reason or "no_supporting_evidence_selected"
            warnings.append(
                WarningItem(
                    code="no_supporting_evidence_selected",
                    message="Tool-based evidence selection returned no supporting source records for this question.",
                )
            )
            response = AgentForgeResponse(
                answer=_focused_uncertainty_answer(request.message),
                sections=[],
                claims=[],
                sources=[],
                warnings=warnings,
                blocked_claims=[],
                verification_status="partial",
                trace_id=trace_id,
            )
            diagnostics = ProviderDiagnostics(
                tool_call_count=tool_diag.tool_call_count,
                selected_source_count=0,
                fallback_reason=reason,
                planning_latency_ms=tool_diag.planning_latency_ms,
                compose_latency_ms=0,
            )
            return response, diagnostics

        compose_payload = {
            "schema_version": request.schema_version,
            "request_id": request.request_id,
            "conversation_id": request.conversation_id,
            "message": request.message,
            "selected_source_ids": [source.id for source in selected_sources],
            "selected_sources": [source.model_dump() for source in selected_sources],
            "adapter_status": [status.model_dump() for status in request.evidence_bundle.adapter_status],
            "drafted_claims": [claim.model_dump() for claim in tool_plan.drafted_claims],
        }

        compose_started = time.perf_counter()
        compose_response = client.responses.parse(
            model=model,
            max_output_tokens=2600,
            input=[
                {"role": "system", "content": COMPOSE_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Return a JSON response matching AgentForgeResponse using only this selected-evidence payload:\n"
                        + json.dumps(compose_payload, separators=(",", ":"))
                    ),
                },
            ],
            text_format=AgentForgeResponse,
        )
        parsed = compose_response.output_parsed
        if not parsed:
            raise RuntimeError("OpenAI response did not include parsed AgentForgeResponse output")
        compose_latency_ms = int((time.perf_counter() - compose_started) * 1000)
        normalized = _limit_response(parsed.model_copy(update={"trace_id": trace_id}), selected_sources)
        if tool_diag.invalid_source_id_count > 0:
            normalized = normalized.model_copy(
                update={
                    "warnings": normalized.warnings
                    + [
                        WarningItem(
                            code="invalid_tool_source_ids_removed",
                            message="Tool phase returned unknown source ids that were removed before response composition.",
                        )
                    ]
                }
            )
        diagnostics = ProviderDiagnostics(
            tool_call_count=tool_diag.tool_call_count,
            selected_source_count=len(selected_sources),
            fallback_reason=tool_diag.fallback_reason,
            planning_latency_ms=tool_diag.planning_latency_ms,
            compose_latency_ms=compose_latency_ms,
        )
        return normalized, diagnostics
    except Exception:  # pragma: no cover - runtime/model-path safeguard
        return _provider_partial_fallback(
            request=request,
            trace_id=trace_id,
            warning_code="provider_exception",
            warning_message="Model processing returned a controlled partial fallback.",
            fallback_reason="provider_exception",
        )


def _limit_response(response: AgentForgeResponse, selected_sources) -> AgentForgeResponse:
    selected_ids = {source.id for source in selected_sources}
    kept_claims = []
    kept_source_ids: list[str] = []
    kept_claim_ids = set()

    for claim in response.claims:
        candidate_source_ids = [
            source_id for source_id in claim.source_ids if source_id in selected_ids and source_id not in kept_source_ids
        ]
        if not candidate_source_ids:
            continue
        if len(kept_claims) >= 8 or len(kept_source_ids) + len(candidate_source_ids) > 10:
            continue
        kept_claims.append(claim.model_copy(update={"source_ids": candidate_source_ids}))
        kept_claim_ids.add(claim.id)
        kept_source_ids.extend(candidate_source_ids)

    response_sources = []
    for source in response.sources:
        if source.id in kept_source_ids and len(response_sources) < 10:
            response_sources.append(source)

    sections = []
    for section in response.sections:
        claim_ids = [claim_id for claim_id in section.claim_ids if claim_id in kept_claim_ids]
        if claim_ids:
            sections.append(section.model_copy(update={"claim_ids": claim_ids}))

    return response.model_copy(
        update={
            "claims": kept_claims,
            "sections": sections,
            "sources": response_sources,
        }
    )


def _selected_sources(request: AgentForgeRequest, source_ids: list[str]):
    source_by_id = {source.id: source for source in request.evidence_bundle.sources}
    selected = []
    for source_id in source_ids:
        source = source_by_id.get(source_id)
        if not source:
            continue
        if any(existing.id == source.id for existing in selected):
            continue
        selected.append(source)
        if len(selected) >= 10:
            break
    return selected


def _focused_uncertainty_answer(message: str) -> str:
    normalized = " ".join(message.strip().split()).rstrip("?.")
    focus = normalized or "the requested topic"
    return f'I did not find retrieved evidence for "{focus}" in the bounded records; confirm in the chart.'


def _provider_partial_fallback(
    request: AgentForgeRequest,
    trace_id: str,
    warning_code: str,
    warning_message: str,
    fallback_reason: str,
) -> tuple[AgentForgeResponse, ProviderDiagnostics]:
    response = AgentForgeResponse(
        answer=_focused_uncertainty_answer(request.message),
        sections=[],
        claims=[],
        sources=[],
        warnings=[WarningItem(code=warning_code, message=warning_message)],
        blocked_claims=[],
        verification_status="partial",
        trace_id=trace_id,
    )
    diagnostics = ProviderDiagnostics(fallback_reason=fallback_reason)
    return response, diagnostics
