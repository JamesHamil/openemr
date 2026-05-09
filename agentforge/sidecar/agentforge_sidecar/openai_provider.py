from __future__ import annotations

import json
import re
import time
import hashlib
from dataclasses import dataclass, replace
from typing import Literal

from pydantic import Field

from .clinical_planner import EvidencePlan, plan_evidence
from .observability import generation_observation, update_generation_observation
from .schemas import (
    AgentForgeRequest,
    AgentForgeResponse,
    ClaimDraft,
    Claim,
    EvidenceSource,
    ResponseSection,
    ResponseSource,
    StrictModel,
    ToolPhaseResult,
    WarningItem,
)
from .settings import Settings
from .tool_agent import ToolPhaseDiagnostics, _usage_tokens, run_tool_phase, search_sources


PHONE_FIELD_LABELS = {
    "phone": "Patient phone",
    "patient_phone": "Patient phone",
    "emergency_contact_phone": "Emergency contact phone",
    "pharmacy_phone": "Pharmacy phone",
}
CONTACT_FIELD_LABELS = {
    "emergency_contact_name": "Emergency contact",
    "emergency_contact_phone": "Emergency contact phone",
}
PHONE_FIELD_ORDER = {
    "phone": 0,
    "patient_phone": 0,
    "emergency_contact_phone": 1,
    "pharmacy_phone": 2,
}
CONTACT_FIELD_ORDER = {
    "emergency_contact_name": 0,
    "emergency_contact_phone": 1,
}
PHONE_PATTERN = re.compile(r"(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}")
LAB_DOCUMENT_FACT_TERMS = (
    "lab",
    "labs",
    "cbc",
    "blood count",
    "differential",
    "morphology",
    "smear",
    "glucose",
    "creatinine",
    "a1c",
    "hemoglobin",
    "hematocrit",
    "platelet",
    "leukocyte",
    "lymphocyte",
    "monocyte",
    "neutrophil",
    "blast",
    "promyelocyte",
    "metamyelocyte",
)


DEFAULT_SELECTED_SOURCE_LIMIT = 10
COMPLETE_MEDICATION_LIST_SOURCE_LIMIT = 24


COMPOSE_PROMPT = """You are AgentForge Clinical Co-Pilot for a hospitalist preparing for rounds.
Use only the selected evidence provided in this request payload. Never provide treatment directives,
orders, diagnoses, or medication changes. Every factual clinical claim must cite source_ids from selected evidence.

You will receive an evidence_plan with an answer_family and clinical rubric. Use it to decide what evidence matters,
not as a canned template. Write naturally for a physician. Do not copy the rubric wording unless it fits the answer.

Keep the answer concise and physician-natural: <=180 words, <=8 claims, <=10 displayed sources.
Exception: for med_reconciliation questions that include selected medication_list document facts, include every selected
medication_list medication fact, even when that requires slightly more than 180 words and up to 24 claims/displayed sources.
Start answer with a direct natural-language response to the specific question.
Avoid unrelated chart inventory unless directly needed for the question.
Do not mark the response partial just because unrelated data is absent; partial is for relevant missing evidence, failed citations, or incomplete answers.
If evidence is limited or an important adapter is unavailable, include one short clinician guidance sentence about what to confirm in chart.
Put general clinician caveats, confirm/review language, and safety guidance in answer or warnings, not in claims, unless the wording is directly supported by selected evidence.
Use compact inline citations only when useful (for example [problem-12]).
For narrow follow-up questions, sections may be empty and claims may be minimal.
For broad chart-summary requests, include sections with scannable claims.
For extracted document or intake-form questions, answer directly from selected document facts;
do not include unrelated chart inventory, unrelated guideline material, or unrelated missing adapters.
For first-room questions, start with today's symptoms or the patient's main concern, then add chart-specific follow-ups.
For cardiac questions, separate explicit cardiac diagnoses from risk-related conditions and cite vitals when selected.
For missing-data questions, name missing data first, then cite any available context second.
For change-since-review questions, compare selected notes directly and preserve direction/timing language.
For red-flag questions, mention each selected problem-list item that may need active-vs-historical verification.
For first-room questions, explicitly ask about current medication use.
Use answer for the top-line response and claims/sections for supporting details.
Return only sources that are cited by claims. Keep each extracted_value short.
Say evidence was not found in retrieved records rather than absent from reality."""

VERIFIER_PROMPT = """You are the AgentForge citation verifier.
Check whether the draft answer is supported by selected chart evidence and follows the evidence_plan.
Do not add clinical facts. Return structured verification only.

Mark result as:
- passed: all factual claims are source-backed and the answer covers the question well enough.
- repairable: there are missing citations, overclaims, or missing expected elements that can be fixed using selected evidence.
- failed: the selected evidence cannot support a useful answer to this question.

Use question-scoped status semantics: missing unrelated adapters are warnings, not automatic partial.
For extracted document or intake-form questions, verify only against selected document facts and patient-identity sources.
Recommend partial only when relevant evidence is unavailable, citations remain unsupported, or the answer is incomplete for the question."""

REPAIR_PROMPT = """Revise the AgentForgeResponse using only the selected evidence and verifier feedback.
Keep the prose natural, concise, and source-cited. Remove unsupported claims instead of weakening citations.
Preserve useful supported content whenever possible."""


_RESPONSE_CACHE: dict[str, tuple[float, AgentForgeResponse, ProviderDiagnostics]] = {}


class ModelVerificationResult(StrictModel):
    result: Literal["passed", "repairable", "failed"]
    issues: list[str] = Field(default_factory=list)
    unsupported_claim_ids: list[str] = Field(default_factory=list)
    missing_expected_elements: list[str] = Field(default_factory=list)
    status_recommendation: Literal["verified", "partial", "refused", "failed"] = "verified"
    citation_coverage: float = 0.0


class ModelResponseSource(StrictModel):
    id: str
    record_type: str
    display: str
    recorded_at: str
    field_path: str
    extracted_value: str


class ModelAgentForgeResponse(StrictModel):
    schema_version: Literal["agentforge.response.v1"] = "agentforge.response.v1"
    answer: str
    sections: list[ResponseSection] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    sources: list[ModelResponseSource] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)
    blocked_claims: list[str] = Field(default_factory=list)
    verification_status: Literal["verified", "partial", "refused", "failed"]
    trace_id: str


@dataclass(frozen=True)
class ProviderDiagnostics:
    tool_call_count: int = 0
    selected_source_count: int = 0
    fallback_reason: str = ""
    planning_latency_ms: int = 0
    compose_latency_ms: int = 0
    answer_family: str = ""
    needed_adapters: tuple[str, ...] = ()
    citation_coverage: float | None = None
    verifier_result: str = ""
    repair_count: int = 0
    status_reason: str = ""
    source_selection_mode: str = ""
    schema_evidence_expansion: dict | None = None
    stale_blocked_claim_count: int = 0
    valid_blocked_claim_count: int = 0
    verify_latency_ms: int = 0
    repair_latency_ms: int = 0
    model_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_strategy: str = ""
    verify_mode: str = ""
    cache_hit: bool = False
    compose_model: str = ""
    verify_model: str = ""


def openai_response(request: AgentForgeRequest, trace_id: str, settings: Settings) -> tuple[AgentForgeResponse, ProviderDiagnostics]:
    model = settings.model
    compose_model = settings.compose_model or settings.model
    verify_model = settings.verify_model or settings.model
    evidence_plan = plan_evidence(request)
    cached = _response_cache_get(request, trace_id, settings)
    if cached is not None:
        return cached
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - depends on runtime dependency
        return _provider_partial_fallback(
            request=request,
            trace_id=trace_id,
            warning_code="openai_runtime_unavailable",
            warning_message=f"OpenAI real mode is not available in this runtime: {exc}",
            fallback_reason="openai_runtime_unavailable",
            evidence_plan=evidence_plan,
        )
    try:
        client = OpenAI()
        schema_expansion: dict = {}
        source_selection_mode = _source_selection_mode(settings, evidence_plan)
        if source_selection_mode in {"planner", "deterministic"}:
            tool_plan = _planner_tool_phase_result(request, evidence_plan)
            tool_diag = ToolPhaseDiagnostics()
            selected_source_ids = list(evidence_plan.selected_source_ids)
        elif source_selection_mode == "model_tool_phase":
            with generation_observation(
                "agentforge.tool_phase",
                settings,
                model,
                {
                    "message": request.message,
                    "source_count": len(request.evidence_bundle.sources),
                    "adapter_statuses": [status.model_dump() for status in request.evidence_bundle.adapter_status],
                    "answer_family": evidence_plan.answer_family,
                    "planner_selected_source_ids": list(evidence_plan.selected_source_ids),
                },
            ) as tool_observation:
                tool_plan, tool_diag = run_tool_phase(client, request, model, settings.reasoning)
                selected_source_ids = _merge_source_ids(
                    evidence_plan.selected_source_ids,
                    tool_plan.selected_source_ids,
                    limit=_selected_source_limit(evidence_plan),
                )
                update_generation_observation(
                    tool_observation,
                    settings,
                    {
                        "selected_source_ids": selected_source_ids,
                        "selected_source_count": len(selected_source_ids),
                        "drafted_claim_count": len(tool_plan.drafted_claims),
                        "focus": tool_plan.focus,
                        "answer_family": evidence_plan.answer_family,
                        "source_selection_mode": source_selection_mode,
                    },
                    metadata={
                        "tool_call_count": tool_diag.tool_call_count,
                        "planning_latency_ms": tool_diag.planning_latency_ms,
                        "fallback_reason": tool_diag.fallback_reason,
                        "invalid_source_id_count": tool_diag.invalid_source_id_count,
                        "model_call_count": tool_diag.model_call_count,
                        "needed_adapters": ",".join(evidence_plan.needed_adapters),
                        "source_selection_mode": source_selection_mode,
                    },
                )
        selected_sources = _selected_sources(request, selected_source_ids, _selected_source_limit(evidence_plan))
        selected_source_ids, selected_sources, schema_expansion = _apply_schema_evidence_expansion(
            request,
            evidence_plan,
            selected_source_ids,
            selected_sources,
        )
        if schema_expansion.get("groups"):
            source_selection_mode = f"{source_selection_mode}+schema_evidence_expansion"
        if not selected_sources:
            warnings = []
            reason = tool_diag.fallback_reason or "no_supporting_evidence_selected"
            warnings.append(
                WarningItem(
                    code="no_supporting_evidence_selected",
                    message="Evidence selection returned no supporting source records for this question.",
                )
            )
            response = AgentForgeResponse(
                answer=_fallback_answer_for_plan(request, evidence_plan),
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
                answer_family=evidence_plan.answer_family,
                needed_adapters=evidence_plan.needed_adapters,
                status_reason=reason,
                source_selection_mode=source_selection_mode,
                schema_evidence_expansion=schema_expansion,
                model_call_count=tool_diag.model_call_count,
                input_tokens=tool_diag.input_tokens,
                output_tokens=tool_diag.output_tokens,
                latency_strategy=_latency_strategy(source_selection_mode, "skipped"),
                verify_mode="skipped",
                compose_model=compose_model,
                verify_model=verify_model,
            )
            return _attach_provider_debug(response, diagnostics), diagnostics

        deterministic_response = _deterministic_document_fact_response(
            request,
            evidence_plan,
            selected_sources,
            schema_expansion,
            trace_id,
        )
        if deterministic_response is not None:
            diagnostics = ProviderDiagnostics(
                tool_call_count=tool_diag.tool_call_count,
                selected_source_count=len(selected_sources),
                fallback_reason=tool_diag.fallback_reason,
                planning_latency_ms=tool_diag.planning_latency_ms,
                compose_latency_ms=0,
                answer_family=evidence_plan.answer_family,
                needed_adapters=evidence_plan.needed_adapters,
                citation_coverage=1.0,
                verifier_result="passed",
                repair_count=0,
                status_reason=(
                    "deterministic_lab_answer"
                    if evidence_plan.answer_family == "labs"
                    else "deterministic_document_fact_answer"
                ),
                source_selection_mode=source_selection_mode,
                schema_evidence_expansion=schema_expansion,
                model_call_count=tool_diag.model_call_count,
                input_tokens=tool_diag.input_tokens,
                output_tokens=tool_diag.output_tokens,
                latency_strategy="deterministic_selection+deterministic_answer+deterministic_verify",
                verify_mode="deterministic",
                compose_model=compose_model,
                verify_model=verify_model,
            )
            deterministic_response = _attach_provider_debug(deterministic_response, diagnostics)
            _response_cache_set(request, settings, deterministic_response, diagnostics)
            return deterministic_response, diagnostics

        model_adapter_status = _model_adapter_status(request, evidence_plan)
        compose_payload = {
            "schema_version": request.schema_version,
            "request_id": request.request_id,
            "conversation_id": request.conversation_id,
            "message": request.message,
            "selected_source_ids": [source.id for source in selected_sources],
            "selected_sources": [source.model_dump() for source in selected_sources],
            "adapter_status": [status.model_dump() for status in model_adapter_status],
            "drafted_claims": [claim.model_dump() for claim in tool_plan.drafted_claims],
            "evidence_plan": _plan_payload(evidence_plan),
            "schema_evidence_expansion": schema_expansion,
        }

        with generation_observation(
            "agentforge.compose_response",
            settings,
            compose_model,
            {
                "message": request.message,
                "selected_source_ids": compose_payload["selected_source_ids"],
                "selected_sources": compose_payload["selected_sources"],
                "drafted_claims": compose_payload["drafted_claims"],
            },
        ) as compose_observation:
            compose_started = time.perf_counter()
            compose_response = client.responses.parse(
                model=compose_model,
                reasoning=settings.reasoning,
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
                text_format=ModelAgentForgeResponse,
            )
            compose_model_call_count = 1
            parsed = compose_response.output_parsed
            if not parsed:
                raise RuntimeError("OpenAI response did not include parsed AgentForgeResponse output")
            compose_input_tokens, compose_output_tokens = _usage_tokens(compose_response)
            parsed_response = _model_response_to_agent_response(parsed, trace_id)
            compose_latency_ms = int((time.perf_counter() - compose_started) * 1000)
            normalized = _limit_response(parsed_response, selected_sources)
            stale_blocked_claim_count = _stale_blocked_claim_count(parsed_response, normalized)
            valid_blocked_claim_count = len(normalized.blocked_claims)
            update_generation_observation(
                compose_observation,
                settings,
                {
                    "verification_status": normalized.verification_status,
                    "claim_count": len(normalized.claims),
                    "source_count": len(normalized.sources),
                    "answer": normalized.answer,
                    "stale_blocked_claim_count": stale_blocked_claim_count,
                    "valid_blocked_claim_count": valid_blocked_claim_count,
                    "schema_evidence_expansion": schema_expansion,
                },
                metadata={
                    "compose_latency_ms": compose_latency_ms,
                    "model_call_count": compose_model_call_count,
                    "source_selection_mode": source_selection_mode,
                    "schema_evidence_expansion_groups": ",".join(schema_expansion.get("groups", [])),
                    "schema_evidence_expansion_added_count": len(schema_expansion.get("added_source_ids", [])),
                    "stale_blocked_claim_count": stale_blocked_claim_count,
                    "valid_blocked_claim_count": valid_blocked_claim_count,
                },
            )
        normalized, verification_metadata = _model_verify_and_repair(
            client=client,
            model=verify_model,
            settings=settings,
            request=request,
            response=normalized,
            selected_sources=selected_sources,
            evidence_plan=evidence_plan,
            trace_id=trace_id,
        )
        normalized = _apply_schema_completion_guard(normalized, schema_expansion)
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
        if schema_expansion.get("groups"):
            normalized = normalized.model_copy(
                update={
                    "debug_trace": {
                        **normalized.debug_trace,
                        "schema_evidence_expansion": schema_expansion,
                    }
                }
            )
        diagnostics = ProviderDiagnostics(
            tool_call_count=tool_diag.tool_call_count,
            selected_source_count=len(selected_sources),
            fallback_reason=tool_diag.fallback_reason,
            planning_latency_ms=tool_diag.planning_latency_ms,
            compose_latency_ms=compose_latency_ms,
            answer_family=evidence_plan.answer_family,
            needed_adapters=evidence_plan.needed_adapters,
            citation_coverage=verification_metadata.citation_coverage,
            verifier_result=verification_metadata.result,
            repair_count=verification_metadata.repair_count,
            status_reason=verification_metadata.status_reason,
            source_selection_mode=source_selection_mode,
            schema_evidence_expansion=schema_expansion,
            stale_blocked_claim_count=stale_blocked_claim_count,
            valid_blocked_claim_count=valid_blocked_claim_count,
            verify_latency_ms=verification_metadata.verify_latency_ms,
            repair_latency_ms=verification_metadata.repair_latency_ms,
            model_call_count=tool_diag.model_call_count + compose_model_call_count + verification_metadata.model_call_count,
            input_tokens=tool_diag.input_tokens + compose_input_tokens + verification_metadata.input_tokens,
            output_tokens=tool_diag.output_tokens + compose_output_tokens + verification_metadata.output_tokens,
            latency_strategy=_latency_strategy(source_selection_mode, verification_metadata.mode),
            verify_mode=verification_metadata.mode,
            compose_model=compose_model,
            verify_model=verify_model,
        )
        normalized = _attach_provider_debug(normalized, diagnostics)
        _response_cache_set(request, settings, normalized, diagnostics)
        return normalized, diagnostics
    except Exception:  # pragma: no cover - runtime/model-path safeguard
        return _provider_partial_fallback(
            request=request,
            trace_id=trace_id,
            warning_code="provider_exception",
            warning_message="Model processing returned a controlled partial fallback.",
            fallback_reason="provider_exception",
            evidence_plan=evidence_plan,
        )


@dataclass(frozen=True)
class VerificationMetadata:
    result: str = ""
    citation_coverage: float | None = None
    repair_count: int = 0
    status_reason: str = ""
    verify_latency_ms: int = 0
    repair_latency_ms: int = 0
    model_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    mode: str = ""


def _source_selection_mode(settings: Settings, evidence_plan: EvidencePlan) -> str:
    if settings.source_selection_mode == "model":
        return "model_tool_phase"
    if settings.source_selection_mode == "deterministic":
        return "deterministic"
    if evidence_plan.answer_family == "labs":
        return "planner" if evidence_plan.selected_source_ids else "deterministic"
    if evidence_plan.confidence >= 0.5 and (evidence_plan.selected_source_ids or evidence_plan.answer_family == "document_facts"):
        return "planner"
    if evidence_plan.selected_source_ids and evidence_plan.answer_family in {"long_tail", "broad_brief", "labs"}:
        return "deterministic"
    return "model_tool_phase"


def _deterministic_verify_metadata(
    response: AgentForgeResponse,
    selected_sources: list[EvidenceSource],
) -> VerificationMetadata:
    started = time.perf_counter()
    selected_ids = {source.id for source in selected_sources}
    response_source_ids = {source.id for source in response.sources}
    issues = []

    unknown_response_sources = sorted(source_id for source_id in response_source_ids if source_id not in selected_ids)
    if unknown_response_sources:
        issues.append("response_sources_not_selected")

    for claim in response.claims:
        if claim.support_status != "supported":
            issues.append("claim_not_supported")
            continue
        if not claim.source_ids:
            issues.append("claim_missing_citation")
            continue
        missing = [
            source_id
            for source_id in claim.source_ids
            if source_id not in selected_ids or source_id not in response_source_ids
        ]
        if missing:
            issues.append("claim_unknown_citation")

    result = "passed" if not issues else "repairable"
    return VerificationMetadata(
        result=result,
        citation_coverage=_code_citation_coverage(response),
        repair_count=0,
        status_reason="deterministic_verifier_passed" if result == "passed" else ",".join(sorted(set(issues))),
        verify_latency_ms=int((time.perf_counter() - started) * 1000),
        model_call_count=0,
        mode="deterministic",
    )


def _should_use_model_verifier(
    settings: Settings,
    evidence_plan: EvidencePlan,
    selected_sources: list[EvidenceSource],
    deterministic_metadata: VerificationMetadata,
) -> bool:
    if settings.verify_mode == "deterministic":
        return False
    if settings.verify_mode == "model":
        return True
    if deterministic_metadata.result != "passed":
        return True
    if evidence_plan.answer_family in {"red_flags", "first_room", "change_since_review"}:
        return True
    if evidence_plan.answer_family == "broad_brief" and len(selected_sources) < 2:
        return True
    return False


def _latency_strategy(source_selection_mode: str, verify_mode: str) -> str:
    selection = "model_tool" if source_selection_mode.startswith("model_tool_phase") else "deterministic_selection"
    verification = "model_verify" if verify_mode == "model" else "deterministic_verify"
    return f"{selection}+compose+{verification}"


def _response_cache_get(
    request: AgentForgeRequest,
    trace_id: str,
    settings: Settings,
) -> tuple[AgentForgeResponse, ProviderDiagnostics] | None:
    if not settings.response_cache_enabled:
        return None
    key = _response_cache_key(request, settings)
    now = time.time()
    cached = _RESPONSE_CACHE.get(key)
    if cached is None:
        return None
    expires_at, response, diagnostics = cached
    if expires_at < now:
        _RESPONSE_CACHE.pop(key, None)
        return None
    cached_diagnostics = replace(
        diagnostics,
        cache_hit=True,
        latency_strategy="cache_hit",
        verify_mode="cache_hit",
        model_call_count=0,
        input_tokens=0,
        output_tokens=0,
        planning_latency_ms=0,
        compose_latency_ms=0,
        verify_latency_ms=0,
        repair_latency_ms=0,
    )
    cached_response = response.model_copy(deep=True, update={"trace_id": trace_id})
    return _attach_provider_debug(cached_response, cached_diagnostics), cached_diagnostics


def _response_cache_set(
    request: AgentForgeRequest,
    settings: Settings,
    response: AgentForgeResponse,
    diagnostics: ProviderDiagnostics,
) -> None:
    if not settings.response_cache_enabled or response.verification_status not in {"verified", "partial"}:
        return
    key = _response_cache_key(request, settings)
    _RESPONSE_CACHE[key] = (
        time.time() + settings.response_cache_ttl_seconds,
        response.model_copy(deep=True),
        diagnostics,
    )


def _response_cache_key(request: AgentForgeRequest, settings: Settings) -> str:
    normalized_message = " ".join(request.message.lower().split())
    material = "|".join(
        [
            request.scope.evidence_bundle_id,
            request.evidence_bundle.id,
            normalized_message,
            settings.model,
            settings.compose_model or settings.model,
            settings.verify_model or settings.model,
            settings.source_selection_mode,
            settings.verify_mode,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _planner_tool_phase_result(request: AgentForgeRequest, evidence_plan: EvidencePlan) -> ToolPhaseResult:
    return _source_ids_tool_phase_result(
        request,
        list(evidence_plan.selected_source_ids),
        _planner_focus(evidence_plan),
    )


def _source_ids_tool_phase_result(
    request: AgentForgeRequest,
    selected_source_ids: list[str] | tuple[str, ...],
    focus: str,
) -> ToolPhaseResult:
    source_by_id = {source.id: source for source in request.evidence_bundle.sources}
    selected_sources = [
        source_by_id[source_id]
        for source_id in selected_source_ids
        if source_id in source_by_id
    ][:8]
    return ToolPhaseResult(
        selected_source_ids=list(selected_source_ids),
        drafted_claims=[
            ClaimDraft(
                text=_draft_claim_text(source),
                claim_type=source.record_type,
                source_ids=[source.id],
            )
            for source in selected_sources
        ],
        focus=focus,
    )


def _apply_schema_evidence_expansion(
    request: AgentForgeRequest,
    evidence_plan: EvidencePlan,
    selected_source_ids: list[str],
    selected_sources: list[EvidenceSource],
) -> tuple[list[str], list[EvidenceSource], dict]:
    groups: list[str] = []
    expansion_source_ids: list[str] = []
    prefer_exact_group = False

    lab_source_ids = _schema_lab_source_ids_for_plan(request, evidence_plan, selected_sources)
    if lab_source_ids:
        groups.append("labs")
        expansion_source_ids = _merge_source_ids(expansion_source_ids, lab_source_ids)

    contact_source_ids = _schema_intake_contact_source_ids_for_question(request)
    if contact_source_ids:
        groups.append("intake_contact")
        expansion_source_ids = _merge_source_ids(expansion_source_ids, contact_source_ids)
        prefer_exact_group = True
    phone_source_ids = [] if contact_source_ids else _schema_phone_source_ids_for_question(request)
    if phone_source_ids:
        groups.append("phone_numbers")
        expansion_source_ids = _merge_source_ids(expansion_source_ids, phone_source_ids)
        prefer_exact_group = True

    added_source_ids = [source_id for source_id in expansion_source_ids if source_id not in selected_source_ids]
    if prefer_exact_group:
        expanded_source_ids = _merge_source_ids(expansion_source_ids)
        expanded_sources = _selected_sources(request, expanded_source_ids, _selected_source_limit(evidence_plan))
        return (
            expanded_source_ids,
            expanded_sources,
            {
                "groups": groups,
                "added_source_ids": added_source_ids,
                "candidate_source_ids": expansion_source_ids,
                "selected_before_count": len(selected_source_ids),
                "selected_after_count": len(expanded_sources),
                "reason": "schema_field_group_exact_selection",
            },
        )
    if not added_source_ids:
        if not expansion_source_ids:
            return selected_source_ids, selected_sources, {}
        return (
            selected_source_ids,
            selected_sources,
            {
                "groups": groups,
                "added_source_ids": [],
                "candidate_source_ids": expansion_source_ids,
                "selected_before_count": len(selected_source_ids),
                "selected_after_count": len(selected_sources),
                "reason": "schema_field_group_already_selected",
            },
        )

    expanded_source_ids = _merge_source_ids(expansion_source_ids, selected_source_ids)
    expanded_sources = _selected_sources(request, expanded_source_ids, _selected_source_limit(evidence_plan))
    return (
        expanded_source_ids,
        expanded_sources,
        {
            "groups": groups,
            "added_source_ids": added_source_ids,
            "candidate_source_ids": expansion_source_ids,
            "selected_before_count": len(selected_source_ids),
            "selected_after_count": len(expanded_sources),
            "reason": "schema_field_group_completeness",
        },
    )


def _schema_lab_source_ids_for_plan(
    request: AgentForgeRequest,
    evidence_plan: EvidencePlan,
    selected_sources: list[EvidenceSource],
) -> list[str]:
    if evidence_plan.answer_family != "labs" and not _is_lab_question(request.message):
        return []
    if not _plan_needs_lab_augmentation(evidence_plan, selected_sources):
        return []
    return _fallback_source_ids_for_plan(request, evidence_plan)


def _is_lab_question(message: str) -> bool:
    normalized = message.lower()
    return any(term in normalized for term in ("lab", "labs", "cbc", "blood count", "glucose", "creatinine", "a1c"))


def _fallback_source_ids_for_plan(request: AgentForgeRequest, evidence_plan: EvidencePlan) -> list[str]:
    if evidence_plan.answer_family != "labs" and "labs" not in evidence_plan.needed_adapters:
        return []
    matches = search_sources(request, request.message, ["lab"], 6)
    return [
        str(match["id"])
        for match in matches
        if match.get("record_type") in {"lab", "document_fact"}
    ][:6]


def _plan_needs_lab_augmentation(evidence_plan: EvidencePlan, selected_sources: list[EvidenceSource]) -> bool:
    if evidence_plan.answer_family != "labs" and "labs" not in evidence_plan.needed_adapters:
        return False
    lab_like_count = sum(
        1
        for source in selected_sources
        if source.record_type in {"lab", "document_fact"}
    )
    return lab_like_count < 4


def _schema_intake_contact_source_ids_for_question(request: AgentForgeRequest) -> list[str]:
    normalized = " ".join(request.message.lower().split())
    if "emergency contact" not in normalized:
        return []
    matches = [
        source
        for source in request.evidence_bundle.sources
        if _is_relevant_emergency_contact_source(request.message, source)
    ]
    matches.sort(key=_contact_source_sort_key)
    return [source.id for source in matches[:4]]


def _is_relevant_emergency_contact_source(message: str, source: EvidenceSource) -> bool:
    if source.record_type != "document_fact":
        return False
    normalized_message = message.lower()
    if ("intake" in normalized_message or "form" in normalized_message) and source.metadata.get("document_type") not in {
        "intake_form",
        "",
    }:
        return False
    if _normalized_field_key(source) in CONTACT_FIELD_LABELS:
        return True
    haystack = _source_haystack(source)
    return "emergency" in haystack and "contact" in haystack


def _contact_source_sort_key(source: EvidenceSource) -> tuple[int, str, str]:
    field_key = _normalized_field_key(source)
    return (CONTACT_FIELD_ORDER.get(field_key, 9), source.recorded_at, source.id)


def _schema_phone_source_ids_for_question(request: AgentForgeRequest) -> list[str]:
    if not _is_phone_number_question(request.message):
        return []
    matches = [
        source
        for source in request.evidence_bundle.sources
        if _is_relevant_phone_source(request.message, source)
    ]
    matches.sort(key=_phone_source_sort_key)
    return [source.id for source in matches[:6]]


def _is_phone_number_question(message: str) -> bool:
    normalized = message.lower()
    if "phone" not in normalized and "contact number" not in normalized:
        return False
    return any(term in normalized for term in ("all", "number", "numbers", "intake", "form", "contact", "pharmacy"))


def _is_relevant_phone_source(message: str, source: EvidenceSource) -> bool:
    if source.record_type != "document_fact":
        return False
    normalized_message = message.lower()
    if ("intake" in normalized_message or "form" in normalized_message) and source.metadata.get("document_type") not in {
        "intake_form",
        "",
    }:
        return False
    field_id = _citation_field_id(source)
    if field_id in PHONE_FIELD_LABELS:
        return True
    haystack = _source_haystack(source)
    return "phone" in haystack and PHONE_PATTERN.search(haystack) is not None


def _phone_source_sort_key(source: EvidenceSource) -> tuple[int, str, str]:
    field_id = _citation_field_id(source)
    return (PHONE_FIELD_ORDER.get(field_id, 9), source.recorded_at, source.id)


def _phone_label_for_source(source: EvidenceSource) -> str:
    field_id = _citation_field_id(source)
    if field_id in PHONE_FIELD_LABELS:
        return PHONE_FIELD_LABELS[field_id]
    first_part = source.value.split(";", 1)[0].strip()
    return first_part if first_part else "Phone"


def _phone_value_for_source(source: EvidenceSource) -> str:
    match = PHONE_PATTERN.search(source.value)
    if match:
        return match.group(0)
    parts = [part.strip() for part in source.value.split(";") if part.strip()]
    if len(parts) >= 2:
        return parts[1]
    return source.value.strip()


def _source_haystack(source: EvidenceSource) -> str:
    return " ".join(
        [
            source.field_path,
            source.value,
            source.note_span or "",
            " ".join(str(value) for value in source.metadata.values()),
        ]
    ).lower()


def _normalized_field_key(source: EvidenceSource) -> str:
    raw = _citation_field_id(source) or source.field_path.rsplit(".", 1)[-1] or source.value.split(";", 1)[0]
    return _field_alias(raw)


def _draft_claim_text(source: EvidenceSource) -> str:
    record_type = source.record_type.replace("_", " ")
    return f"Retrieved {record_type} evidence: {source.value}."


def _planner_focus(evidence_plan: EvidencePlan) -> str:
    if evidence_plan.rubric:
        return " ".join(evidence_plan.rubric[:2])
    return "Deterministic evidence planner selected relevant sources."


def _limit_response(response: AgentForgeResponse, selected_sources: list[EvidenceSource]) -> AgentForgeResponse:
    selected_ids = {source.id for source in selected_sources}
    selected_by_id = {source.id: source for source in selected_sources}
    kept_claims = []
    kept_source_ids: list[str] = []
    kept_claim_ids = set()

    for claim in response.claims:
        candidate_source_ids = [source_id for source_id in claim.source_ids if source_id in selected_ids]
        if not candidate_source_ids:
            continue
        new_source_ids = [source_id for source_id in candidate_source_ids if source_id not in kept_source_ids]
        if len(kept_claims) >= 8 or len(kept_source_ids) + len(new_source_ids) > 10:
            continue
        kept_claims.append(claim.model_copy(update={"source_ids": candidate_source_ids}))
        kept_claim_ids.add(claim.id)
        kept_source_ids.extend(new_source_ids)

    response_sources = [
        _response_source_from_evidence(selected_by_id[source_id])
        for source_id in kept_source_ids
        if source_id in selected_by_id
    ][:10]

    sections = []
    for section in response.sections:
        claim_ids = [claim_id for claim_id in section.claim_ids if claim_id in kept_claim_ids]
        if claim_ids:
            sections.append(section.model_copy(update={"claim_ids": claim_ids}))
    if not sections and len(kept_claims) >= 3:
        sections = _sections_from_claims(kept_claims)

    blocked_claims = []
    for claim_id in response.blocked_claims:
        if claim_id in kept_claim_ids and claim_id not in blocked_claims:
            blocked_claims.append(claim_id)

    return response.model_copy(
        update={
            "claims": kept_claims,
            "sections": sections,
            "sources": response_sources,
            "blocked_claims": blocked_claims,
        }
    )


def _apply_schema_completion_guard(response: AgentForgeResponse, schema_expansion: dict) -> AgentForgeResponse:
    groups = set(schema_expansion.get("groups", []))
    if not groups & {"phone_numbers", "intake_contact", "pharmacy", "insurance"}:
        return response
    expected_source_ids = set(schema_expansion.get("candidate_source_ids", []))
    if not expected_source_ids:
        return response
    returned_source_ids = {source.id for source in response.sources}
    missing_source_ids = sorted(expected_source_ids - returned_source_ids)
    if not missing_source_ids:
        return response

    warning = WarningItem(
        code="schema_evidence_omitted",
        message=(
            "The model response did not cite every schema-matched source selected for this field-group question: "
            + ", ".join(missing_source_ids)
        ),
    )
    status = "partial" if response.verification_status == "verified" else response.verification_status
    return response.model_copy(
        update={
            "warnings": response.warnings + [warning],
            "verification_status": status,
            "debug_trace": {
                **response.debug_trace,
                "schema_evidence_completion": {
                    "expected_source_ids": sorted(expected_source_ids),
                    "missing_source_ids": missing_source_ids,
                },
            },
        }
    )


def _deterministic_document_fact_response(
    request: AgentForgeRequest,
    evidence_plan: EvidencePlan,
    selected_sources: list[EvidenceSource],
    schema_expansion: dict,
    trace_id: str,
) -> AgentForgeResponse | None:
    if evidence_plan.answer_family == "labs":
        return _deterministic_lab_response(request, selected_sources, trace_id)
    if evidence_plan.answer_family != "document_facts":
        return None
    document_sources = [source for source in selected_sources if source.record_type == "document_fact"]
    if not document_sources or not _is_direct_document_fact_lookup(request, document_sources, schema_expansion):
        return None

    groups = set(schema_expansion.get("groups", []))
    answer = _direct_document_fact_answer(request.message, document_sources, groups)
    claims = [
        Claim(
            id=f"claim-{index + 1}",
            text=f"{_document_fact_label_value(source)[0]} is {_document_fact_label_value(source)[1]}.",
            claim_type="document_fact",
            source_ids=[source.id],
            support_status="supported",
        )
        for index, source in enumerate(document_sources)
    ]
    return AgentForgeResponse(
        answer=answer,
        sections=[
            ResponseSection(
                id="document-facts",
                title="Extracted Document Facts",
                claim_ids=[claim.id for claim in claims],
            )
        ],
        claims=claims,
        sources=[_response_source_from_evidence(source) for source in document_sources],
        warnings=[],
        blocked_claims=[],
        verification_status="verified",
        trace_id=trace_id,
        debug_trace={
            "deterministic_answer": {
                "reason": "structured_document_fact_lookup",
                "source_ids": [source.id for source in document_sources],
            }
        },
    )


def _deterministic_lab_response(
    request: AgentForgeRequest,
    selected_sources: list[EvidenceSource],
    trace_id: str,
) -> AgentForgeResponse | None:
    lab_sources = [source for source in selected_sources if _is_lab_like_source(source)]
    if not lab_sources:
        return None

    result_phrases = [_lab_fact_phrase(source) for source in lab_sources[:8]]
    answer = "Lab results available: " + "; ".join(result_phrases) + "."
    claims = [
        Claim(
            id=f"claim-{index + 1}",
            text=phrase[0].upper() + phrase[1:] + ".",
            claim_type="lab",
            source_ids=[source.id],
            support_status="supported",
        )
        for index, (source, phrase) in enumerate(zip(lab_sources[:8], result_phrases, strict=False))
    ]
    return AgentForgeResponse(
        answer=answer,
        sections=[
            ResponseSection(
                id="lab-results",
                title="Lab Results",
                claim_ids=[claim.id for claim in claims],
            )
        ],
        claims=claims,
        sources=[_response_source_from_evidence(source) for source in lab_sources[:8]],
        warnings=[],
        blocked_claims=[],
        verification_status="verified",
        trace_id=trace_id,
        debug_trace={
            "deterministic_answer": {
                "reason": "structured_lab_fact_lookup",
                "source_ids": [source.id for source in lab_sources[:8]],
            }
        },
    )


def _is_lab_like_source(source: EvidenceSource) -> bool:
    if source.record_type == "lab":
        return True
    if source.record_type != "document_fact":
        return False
    if source.metadata.get("document_type") == "lab_pdf":
        return True
    haystack = _source_haystack(source)
    return "lab_result" in source.field_path.lower() or any(term in haystack for term in LAB_DOCUMENT_FACT_TERMS)


def _lab_fact_phrase(source: EvidenceSource) -> str:
    label, value, unit, reference_range, abnormal = _lab_fact_parts(source)
    display_value = value
    if unit and unit not in display_value:
        separator = "" if unit == "%" else " "
        display_value = f"{display_value}{separator}{unit}"
    qualifiers = []
    if abnormal:
        qualifiers.append(f"abnormal {abnormal.lower()}")
    if reference_range:
        qualifiers.append(f"reference {reference_range}")
    qualifier_text = f" ({'; '.join(qualifiers)})" if qualifiers else ""
    return f"{label} {display_value}{qualifier_text}"


def _lab_fact_parts(source: EvidenceSource) -> tuple[str, str, str, str, str]:
    parts = [part.strip() for part in source.value.split(";") if part.strip()]
    label = parts[0] if parts else source.field_path.rsplit(".", 1)[-1].replace("_", " ").title()
    value = parts[1] if len(parts) > 1 else source.value.strip()
    unit = ""
    reference_range = ""
    abnormal = ""
    for part in parts[2:]:
        normalized = part.lower().strip()
        if normalized.startswith("unit "):
            unit = part[5:].strip()
        elif normalized.startswith("range "):
            reference_range = part[6:].strip()
        elif normalized.startswith("reference "):
            reference_range = part[10:].strip()
        elif normalized.startswith("abnormal "):
            abnormal = part[9:].strip()
        elif normalized.startswith("flag "):
            abnormal = part[5:].strip()
    return label, value, unit, reference_range, abnormal


def _is_direct_document_fact_lookup(
    request: AgentForgeRequest,
    document_sources: list[EvidenceSource],
    schema_expansion: dict,
) -> bool:
    groups = set(schema_expansion.get("groups", []))
    if groups & {"phone_numbers", "intake_contact", "pharmacy", "insurance"}:
        return True
    if len(document_sources) > 6:
        return False
    normalized = " ".join(request.message.lower().split())
    return any(
        term in normalized
        for term in (
            "phone",
            "contact",
            "pharmacy",
            "medication",
            "medications",
            "med list",
            "medication list",
            "address",
            "email",
            "insurance",
            "policy",
            "signature",
            "signed",
            "date",
        )
    )


def _direct_document_fact_answer(message: str, document_sources: list[EvidenceSource], groups: set[str]) -> str:
    if "intake_contact" in groups or "emergency contact" in message.lower():
        name_source = _first_source_by_field(document_sources, "emergency_contact_name")
        phone_source = _first_source_by_field(document_sources, "emergency_contact_phone")
        name_value = _document_fact_label_value(name_source)[1] if name_source else ""
        phone_value = _document_fact_label_value(phone_source)[1] if phone_source else ""
        if name_value and phone_value:
            return f"Emergency contact is {name_value}; phone {phone_value}."
        if phone_value:
            return f"Emergency contact phone is {phone_value}."
        if name_value:
            return f"Emergency contact is {name_value}."

    facts = []
    for source in document_sources:
        label, value = _document_fact_label_value(source)
        facts.append(f"{label}: {value}")
    return "; ".join(facts) + "."


def _first_source_by_field(sources: list[EvidenceSource], field: str) -> EvidenceSource | None:
    for source in sources:
        if _normalized_field_key(source) == field:
            return source
    return None


def _document_fact_label_value(source: EvidenceSource) -> tuple[str, str]:
    field_key = _normalized_field_key(source)
    if field_key in CONTACT_FIELD_LABELS:
        label = CONTACT_FIELD_LABELS[field_key]
    elif field_key in PHONE_FIELD_LABELS:
        label = PHONE_FIELD_LABELS[field_key]
    else:
        label = source.value.split(";", 1)[0].strip() or source.field_path.rsplit(".", 1)[-1].replace("_", " ").title()

    if field_key in PHONE_FIELD_LABELS:
        return label, _phone_value_for_source(source)
    parts = [part.strip() for part in source.value.split(";", 1)]
    if len(parts) == 2 and parts[1]:
        return label, parts[1]
    return label, source.value.strip()


def _stale_blocked_claim_count(original: AgentForgeResponse, limited: AgentForgeResponse) -> int:
    retained_claim_ids = {claim.id for claim in limited.claims}
    return sum(1 for claim_id in set(original.blocked_claims) if claim_id not in retained_claim_ids)


def _sections_from_claims(claims: list[Claim]) -> list[ResponseSection]:
    sections: list[ResponseSection] = []
    for claim in claims:
        section_id = _section_id_for_claim_type(claim.claim_type)
        existing = next((section for section in sections if section.id == section_id), None)
        if existing:
            existing.claim_ids.append(claim.id)
            continue
        sections.append(
            ResponseSection(
                id=section_id,
                title=claim.claim_type.replace("_", " ").title(),
                claim_ids=[claim.id],
            )
        )
        if len(sections) >= 6:
            break
    return sections


def _section_id_for_claim_type(claim_type: str) -> str:
    normalized = "".join(character if character.isalnum() else "-" for character in claim_type.lower()).strip("-")
    return normalized or "evidence"


def _model_verify_and_repair(
    client,
    model: str,
    settings: Settings,
    request: AgentForgeRequest,
    response: AgentForgeResponse,
    selected_sources: list[EvidenceSource],
    evidence_plan: EvidencePlan,
    trace_id: str,
) -> tuple[AgentForgeResponse, VerificationMetadata]:
    deterministic_metadata = _deterministic_verify_metadata(response, selected_sources)
    if not _should_use_model_verifier(settings, evidence_plan, selected_sources, deterministic_metadata):
        return response, deterministic_metadata

    model_adapter_status = _model_adapter_status(request, evidence_plan)
    verification_payload = {
        "message": request.message,
        "evidence_plan": _plan_payload(evidence_plan),
        "selected_sources": [source.model_dump() for source in selected_sources],
        "adapter_status": [status.model_dump() for status in model_adapter_status],
        "draft_response": response.model_dump(),
    }
    verify_started = time.perf_counter()
    try:
        with generation_observation(
            "agentforge.verify_response",
            settings,
            model,
            verification_payload,
        ) as verify_observation:
            verify_response = client.responses.parse(
                model=model,
                reasoning=settings.reasoning,
                max_output_tokens=900,
                input=[
                    {"role": "system", "content": VERIFIER_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Verify this draft AgentForgeResponse:\n"
                            + json.dumps(verification_payload, separators=(",", ":"))
                        ),
                    },
                ],
                text_format=ModelVerificationResult,
            )
            verify_latency_ms = int((time.perf_counter() - verify_started) * 1000)
            parsed = verify_response.output_parsed
            if not parsed:
                raise RuntimeError("Model verifier did not return parsed output")
            verify_input_tokens, verify_output_tokens = _usage_tokens(verify_response)
            update_generation_observation(
                verify_observation,
                settings,
                parsed.model_dump(),
                metadata={
                    "verifier_result": parsed.result,
                    "citation_coverage": parsed.citation_coverage,
                    "status_recommendation": parsed.status_recommendation,
                    "verify_latency_ms": verify_latency_ms,
                },
            )

        metadata = VerificationMetadata(
            result=parsed.result,
            citation_coverage=parsed.citation_coverage,
            repair_count=0,
            status_reason="model_verifier_passed" if parsed.result == "passed" else "; ".join(parsed.issues[:3]),
            verify_latency_ms=verify_latency_ms,
            model_call_count=1,
            input_tokens=verify_input_tokens,
            output_tokens=verify_output_tokens,
            mode="model",
        )
        if parsed.result == "passed":
            if parsed.status_recommendation != response.verification_status:
                response = response.model_copy(update={"verification_status": parsed.status_recommendation})
            return response, metadata

        repair_started = time.perf_counter()
        repaired = _repair_response(
            client=client,
            model=model,
            settings=settings,
            request=request,
            response=response,
            selected_sources=selected_sources,
            evidence_plan=evidence_plan,
            verification=parsed,
            trace_id=trace_id,
        )
        repair_latency_ms = int((time.perf_counter() - repair_started) * 1000)
        if repaired is None:
            status = "partial" if response.verification_status == "verified" else response.verification_status
            return response.model_copy(update={"verification_status": status}), VerificationMetadata(
                result=parsed.result,
                citation_coverage=parsed.citation_coverage,
                repair_count=0,
                status_reason="model_verifier_unrepaired",
                verify_latency_ms=verify_latency_ms,
                repair_latency_ms=repair_latency_ms,
                model_call_count=2,
                input_tokens=verify_input_tokens,
                output_tokens=verify_output_tokens,
                mode="model",
            )
        repaired_response, repair_input_tokens, repair_output_tokens = repaired
        return repaired_response, VerificationMetadata(
            result=parsed.result,
            citation_coverage=parsed.citation_coverage,
            repair_count=1,
            status_reason="model_verifier_repaired",
            verify_latency_ms=verify_latency_ms,
            repair_latency_ms=repair_latency_ms,
            model_call_count=2,
            input_tokens=verify_input_tokens + repair_input_tokens,
            output_tokens=verify_output_tokens + repair_output_tokens,
            mode="model",
        )
    except Exception:
        return response, VerificationMetadata(
            result="verifier_unavailable",
            citation_coverage=_code_citation_coverage(response),
            repair_count=0,
            status_reason="model_verifier_unavailable",
            verify_latency_ms=int((time.perf_counter() - verify_started) * 1000),
            model_call_count=1,
            mode="model",
        )


def _repair_response(
    client,
    model: str,
    settings: Settings,
    request: AgentForgeRequest,
    response: AgentForgeResponse,
    selected_sources: list[EvidenceSource],
    evidence_plan: EvidencePlan,
    verification: ModelVerificationResult,
    trace_id: str,
) -> tuple[AgentForgeResponse, int, int] | None:
    repair_payload = {
        "message": request.message,
        "evidence_plan": _plan_payload(evidence_plan),
        "selected_sources": [source.model_dump() for source in selected_sources],
        "adapter_status": [status.model_dump() for status in _model_adapter_status(request, evidence_plan)],
        "draft_response": response.model_dump(),
        "verifier_feedback": verification.model_dump(),
    }
    try:
        with generation_observation(
            "agentforge.repair_response",
            settings,
            model,
            repair_payload,
        ) as repair_observation:
            repair_response = client.responses.parse(
                model=model,
                reasoning=settings.reasoning,
                max_output_tokens=1800,
                input=[
                    {"role": "system", "content": REPAIR_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Return a revised AgentForgeResponse:\n"
                            + json.dumps(repair_payload, separators=(",", ":"))
                        ),
                    },
                ],
                text_format=ModelAgentForgeResponse,
            )
            parsed = repair_response.output_parsed
            if not parsed:
                return None
            repair_input_tokens, repair_output_tokens = _usage_tokens(repair_response)
            repaired = _limit_response(_model_response_to_agent_response(parsed, trace_id), selected_sources)
            update_generation_observation(
                repair_observation,
                settings,
                {
                    "verification_status": repaired.verification_status,
                    "claim_count": len(repaired.claims),
                    "source_count": len(repaired.sources),
                    "answer": repaired.answer,
                },
                metadata={"repair_count": 1},
            )
            return repaired, repair_input_tokens, repair_output_tokens
    except Exception:
        return None


def _selected_sources(
    request: AgentForgeRequest,
    source_ids: list[str] | tuple[str, ...],
    limit: int = DEFAULT_SELECTED_SOURCE_LIMIT,
):
    source_by_id = {source.id: source for source in request.evidence_bundle.sources}
    selected = []
    for source_id in source_ids:
        source = source_by_id.get(source_id)
        if not source:
            continue
        if any(existing.id == source.id for existing in selected):
            continue
        selected.append(source)
        if len(selected) >= limit:
            break
    return selected


def _model_response_to_agent_response(response: ModelAgentForgeResponse, trace_id: str) -> AgentForgeResponse:
    return AgentForgeResponse(
        schema_version=response.schema_version,
        answer=response.answer,
        sections=response.sections,
        claims=response.claims,
        sources=[
            ResponseSource(
                id=source.id,
                record_type=source.record_type,
                display=source.display,
                recorded_at=source.recorded_at,
                field_path=source.field_path,
                extracted_value=source.extracted_value,
            )
            for source in response.sources
        ],
        warnings=response.warnings,
        blocked_claims=response.blocked_claims,
        verification_status=response.verification_status,
        trace_id=trace_id,
    )


def _merge_source_ids(
    *source_id_groups: list[str] | tuple[str, ...],
    limit: int = DEFAULT_SELECTED_SOURCE_LIMIT,
) -> list[str]:
    merged: list[str] = []
    for source_ids in source_id_groups:
        for source_id in source_ids:
            if source_id not in merged:
                merged.append(source_id)
            if len(merged) >= limit:
                return merged
    return merged


def _selected_source_limit(evidence_plan: EvidencePlan) -> int:
    if evidence_plan.answer_family in {"med_reconciliation", "document_facts"}:
        if any(
            "document-fact" in source_id
            for source_id in evidence_plan.selected_source_ids
        ):
            return COMPLETE_MEDICATION_LIST_SOURCE_LIMIT
    return DEFAULT_SELECTED_SOURCE_LIMIT


def _plan_payload(plan: EvidencePlan) -> dict:
    return {
        "answer_family": plan.answer_family,
        "secondary_families": list(plan.secondary_families),
        "confidence": plan.confidence,
        "required_adapters": list(plan.required_adapters),
        "context_adapters": list(plan.context_adapters),
        "needed_adapters": list(plan.needed_adapters),
        "preferred_record_types": list(plan.preferred_record_types),
        "planner_selected_source_ids": list(plan.selected_source_ids),
        "rubric": list(plan.rubric),
    }


def _model_adapter_status(request: AgentForgeRequest, evidence_plan: EvidencePlan):
    if evidence_plan.answer_family == "document_facts":
        scoped = [
            status
            for status in request.evidence_bundle.adapter_status
            if status.adapter == "agentforge_documents"
        ]
        return scoped or request.evidence_bundle.adapter_status
    if evidence_plan.answer_family == "labs":
        scoped = [
            status
            for status in request.evidence_bundle.adapter_status
            if status.adapter in {"labs", "agentforge_documents"}
        ]
        return scoped or request.evidence_bundle.adapter_status
    return request.evidence_bundle.adapter_status


def _attach_provider_debug(response: AgentForgeResponse, diagnostics: ProviderDiagnostics) -> AgentForgeResponse:
    debug_trace = dict(response.debug_trace)
    debug_trace["provider"] = {
        "answer_family": diagnostics.answer_family,
        "source_selection_mode": diagnostics.source_selection_mode,
        "selected_source_count": diagnostics.selected_source_count,
        "tool_call_count": diagnostics.tool_call_count,
        "model_call_count": diagnostics.model_call_count,
        "planning_latency_ms": diagnostics.planning_latency_ms,
        "compose_latency_ms": diagnostics.compose_latency_ms,
        "verify_latency_ms": diagnostics.verify_latency_ms,
        "repair_latency_ms": diagnostics.repair_latency_ms,
        "verifier_result": diagnostics.verifier_result,
        "repair_count": diagnostics.repair_count,
        "input_tokens": diagnostics.input_tokens,
        "output_tokens": diagnostics.output_tokens,
        "fallback_reason": diagnostics.fallback_reason,
        "latency_strategy": diagnostics.latency_strategy,
        "verify_mode": diagnostics.verify_mode,
        "cache_hit": diagnostics.cache_hit,
        "compose_model": diagnostics.compose_model,
        "verify_model": diagnostics.verify_model,
    }
    return response.model_copy(update={"debug_trace": debug_trace})


def _response_source_from_evidence(source: EvidenceSource) -> ResponseSource:
    status = source.metadata.get("status", "")
    display_prefix = f"{status.title()} " if status else ""
    extracted_value = source.value
    if source.record_type == "document_fact" and _citation_field_id(source) in PHONE_FIELD_LABELS:
        extracted_value = f"{_phone_label_for_source(source)}; {_phone_value_for_source(source)}"
    return ResponseSource(
        id=source.id,
        record_type=source.record_type,
        display=f"{display_prefix}{source.record_type.replace('_', ' ').title()} source",
        recorded_at=source.recorded_at,
        field_path=source.field_path,
        extracted_value=extracted_value,
        metadata=source.metadata,
    )


def _citation_field_id(source: EvidenceSource) -> str:
    citation = _citation_payload(source)
    return _field_alias(str(citation.get("field_or_chunk_id", "")).strip())


def _field_alias(raw: str) -> str:
    if not raw:
        return ""
    normalized = "".join(character.lower() for character in raw if character.isalnum())
    aliases = {
        "emergencycontactname": "emergency_contact_name",
        "emergencycontactphone": "emergency_contact_phone",
        "emergencycontactrelationship": "emergency_contact_relationship",
        "relationshiptopatient": "emergency_contact_relationship",
        "patientphone": "patient_phone",
        "phone": "phone",
        "pharmacyphone": "pharmacy_phone",
        "phonenumber": "phone",
    }
    return aliases.get(normalized, raw.strip().lower())


def _citation_payload(source: EvidenceSource) -> dict:
    raw = source.metadata.get("citation", "")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _code_citation_coverage(response: AgentForgeResponse) -> float:
    if not response.claims:
        return 0.0
    cited = sum(1 for claim in response.claims if claim.source_ids)
    return round(cited / len(response.claims), 3)


def _focused_uncertainty_answer(message: str) -> str:
    normalized = " ".join(message.strip().split()).rstrip("?.")
    focus = normalized or "the requested topic"
    return f'I did not find retrieved evidence for "{focus}" in the bounded records; confirm in the chart.'


def _fallback_answer_for_plan(request: AgentForgeRequest, evidence_plan: EvidencePlan) -> str:
    if evidence_plan.answer_family == "missing_data":
        missing = _unavailable_adapter_names(request, evidence_plan)
        if missing:
            return f"Missing retrieved data includes {', '.join(missing)}; confirm in chart before final decisions."
        return "No selected sources were available for this missing-data question; confirm the needed clinical context in the chart."
    return _focused_uncertainty_answer(request.message)


def _unavailable_adapter_names(request: AgentForgeRequest, evidence_plan: EvidencePlan) -> list[str]:
    status_by_adapter = {status.adapter: status.status for status in request.evidence_bundle.adapter_status}
    names = []
    for adapter in evidence_plan.needed_adapters:
        if status_by_adapter.get(adapter) not in {"success", "partial"}:
            names.append(adapter.replace("_", " "))
    return names


def _provider_partial_fallback(
    request: AgentForgeRequest,
    trace_id: str,
    warning_code: str,
    warning_message: str,
    fallback_reason: str,
    evidence_plan: EvidencePlan | None = None,
) -> tuple[AgentForgeResponse, ProviderDiagnostics]:
    response = AgentForgeResponse(
        answer=_fallback_answer_for_plan(request, evidence_plan or plan_evidence(request)),
        sections=[],
        claims=[],
        sources=[],
        warnings=[WarningItem(code=warning_code, message=warning_message)],
        blocked_claims=[],
        verification_status="partial",
        trace_id=trace_id,
    )
    diagnostics = ProviderDiagnostics(
        fallback_reason=fallback_reason,
        answer_family=evidence_plan.answer_family if evidence_plan else "",
        needed_adapters=evidence_plan.needed_adapters if evidence_plan else (),
        status_reason=fallback_reason,
        latency_strategy="fallback",
        verify_mode="skipped",
        compose_model=settings.compose_model or settings.model,
        verify_model=settings.verify_model or settings.model,
    )
    return _attach_provider_debug(response, diagnostics), diagnostics
