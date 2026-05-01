from __future__ import annotations

from .clinical_planner import EvidencePlan, missing_required_adapters, plan_evidence
from .schemas import AgentForgeRequest, AgentForgeResponse, Claim, ResponseStatus, WarningItem


TREATMENT_DIRECTIVE_TERMS = (
    "start ",
    "stop ",
    "continue ",
    "discontinue ",
    "prescribe",
    "increase dose",
    "decrease dose",
    "hold ",
    "administer ",
)

PROMPT_INJECTION_TERMS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "developer message",
    "override policy",
    "forget instructions",
)


def is_treatment_directive(message: str) -> bool:
    normalized = f" {message.lower()} "
    return any(term in normalized for term in TREATMENT_DIRECTIVE_TERMS)


def has_prompt_injection_text(text: str) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in PROMPT_INJECTION_TERMS)


def adapter_warnings(request: AgentForgeRequest) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    for status in request.evidence_bundle.adapter_status:
        if status.status != "success":
            reason = f": {status.reason}" if status.reason else ""
            display = status.adapter.replace("_", " ")
            warnings.append(
                WarningItem(
                    code=f"collector_{status.status}",
                    message=f"{display.title()} data was {status.status} in retrieved OpenEMR records{reason}.",
                )
            )
    return warnings


def verify_response(
    request: AgentForgeRequest,
    response: AgentForgeResponse,
    evidence_plan: EvidencePlan | None = None,
) -> AgentForgeResponse:
    evidence_plan = evidence_plan or plan_evidence(request)
    source_by_id = {source.id: source for source in request.evidence_bundle.sources}
    response_source_ids = {source.id for source in response.sources}
    blocked: list[str] = list(response.blocked_claims)
    checked_claims: list[Claim] = []
    prompt_injection_found = False

    for claim in response.claims:
        if claim.support_status != "supported":
            blocked.append(claim.id)
            checked_claims.append(claim.model_copy(update={"support_status": "blocked"}))
            continue

        if not claim.source_ids:
            if _adapter_gap_claim_is_supported(claim, request, evidence_plan):
                checked_claims.append(claim)
                continue
            if _first_room_guidance_claim_is_supported(claim, evidence_plan):
                checked_claims.append(claim)
                continue
            blocked.append(claim.id)
            checked_claims.append(claim.model_copy(update={"support_status": "blocked"}))
            continue

        missing_sources = [
            source_id
            for source_id in claim.source_ids
            if source_id not in source_by_id or source_id not in response_source_ids
        ]
        if missing_sources:
            blocked.append(claim.id)
            checked_claims.append(claim.model_copy(update={"support_status": "blocked"}))
            continue

        if not _claim_has_source_overlap(claim, [source_by_id[source_id].value for source_id in claim.source_ids]):
            blocked.append(claim.id)
            checked_claims.append(claim.model_copy(update={"support_status": "blocked"}))
            continue

        checked_claims.append(claim)

    warnings = response.warnings + adapter_warnings(request)
    for source in request.evidence_bundle.sources:
        if has_prompt_injection_text(source.value) or (source.note_span and has_prompt_injection_text(source.note_span)):
            prompt_injection_found = True
            warnings.append(
                WarningItem(
                    code="prompt_injection_in_chart_text",
                    message="Retrieved chart text contained instruction-like content and was treated only as patient-record evidence.",
                )
            )
            break

    status: ResponseStatus = response.verification_status
    display_claims = checked_claims
    display_sections = response.sections
    display_sources = response.sources
    answer = response.answer
    if blocked:
        supported_claims = [claim for claim in checked_claims if claim.support_status == "supported"]
        blocked_claims = [claim for claim in checked_claims if claim.support_status == "blocked"]
        supported_claim_ids = {claim.id for claim in supported_claims}
        supported_source_ids = {
            source_id
            for claim in supported_claims
            for source_id in claim.source_ids
        }
        display_claims = supported_claims
        display_sections = [
            section.model_copy(
                update={
                    "claim_ids": [
                        claim_id for claim_id in section.claim_ids if claim_id in supported_claim_ids
                    ]
                }
            )
            for section in response.sections
            if any(claim_id in supported_claim_ids for claim_id in section.claim_ids)
        ]
        display_sources = [source for source in response.sources if source.id in supported_source_ids]
        if _can_preserve_answer_after_blocking(evidence_plan, supported_claims, blocked_claims):
            answer = response.answer
        else:
            answer = _safe_answer_after_blocking(supported_claims, request.message)
        status = "partial"
    if missing_required_adapters(request, evidence_plan) and status == "verified":
        status = "partial"
    if prompt_injection_found and status == "verified":
        status = "partial"

    return response.model_copy(
        update={
            "answer": answer,
            "sections": display_sections,
            "claims": display_claims,
            "sources": display_sources,
            "warnings": warnings,
            "blocked_claims": sorted(set(blocked)),
            "verification_status": status,
        }
    )


def _claim_has_source_overlap(claim: Claim, values: list[str]) -> bool:
    claim_words = _important_words(claim.text)
    if not claim_words:
        return False
    source_words = set()
    for value in values:
        source_words.update(_important_words(value))
    return bool(claim_words & source_words)


def _adapter_gap_claim_is_supported(claim: Claim, request: AgentForgeRequest, evidence_plan: EvidencePlan) -> bool:
    if evidence_plan.answer_family != "missing_data":
        return False
    if claim.claim_type not in {"missing_data", "gap", "guidance", "adapter_status"}:
        return False

    normalized = claim.text.lower()
    if not any(term in normalized for term in ("missing", "unavailable", "not provided", "not visible", "need", "review", "confirm")):
        return False

    status_by_adapter = {status.adapter: status.status for status in request.evidence_bundle.adapter_status}
    missing_adapters = {
        adapter
        for adapter in evidence_plan.needed_adapters
        if status_by_adapter.get(adapter) not in {"success", "partial"}
    }
    if not missing_adapters:
        return False

    adapter_terms = {
        "medications": ("medication", "medications", "med", "meds"),
        "vitals": ("vital", "vitals"),
        "labs": ("lab", "labs", "laboratory"),
        "recent_notes": ("note", "notes", "assessment", "encounter"),
        "problem_list": ("problem", "condition", "conditions", "diagnosis", "diagnoses"),
        "allergies": ("allergy", "allergies"),
    }
    return any(
        any(term in normalized for term in adapter_terms.get(adapter, (adapter.replace("_", " "),)))
        for adapter in missing_adapters
    )


def _first_room_guidance_claim_is_supported(claim: Claim, evidence_plan: EvidencePlan) -> bool:
    if evidence_plan.answer_family != "first_room":
        return False
    if claim.claim_type not in {"guidance", "question_sequence", "first_room", "question"}:
        return False

    normalized = claim.text.lower()
    if any(term in normalized for term in ("prescribe", "order ", "dose", "administer", "discontinue")):
        return False
    return any(term in normalized for term in ("ask", "confirm", "clarify", "review", "question", "symptom", "history"))


def _can_preserve_answer_after_blocking(
    evidence_plan: EvidencePlan,
    supported_claims: list[Claim],
    blocked_claims: list[Claim],
) -> bool:
    if not supported_claims:
        return False
    if evidence_plan.answer_family not in {"first_room", "missing_data"}:
        return False

    soft_claim_types = {"guidance", "question_sequence", "first_room", "question", "missing_data", "gap", "adapter_status"}
    return all(claim.claim_type in soft_claim_types for claim in blocked_claims)


def _safe_answer_after_blocking(claims: list[Claim], message: str) -> str:
    if not claims:
        return _focused_uncertainty_answer(message)

    top_claims = claims[:3]
    sentences = [_claim_sentence(claim) for claim in top_claims]
    answer = "Based on retrieved chart evidence, " + " ".join(sentences)
    if len(claims) > len(top_claims):
        answer += " Additional supported details are listed below."
    return answer


def _focused_uncertainty_answer(message: str) -> str:
    focus = _question_focus(message)
    return f'I did not find retrieved evidence for "{focus}" in the bounded records; confirm in the chart.'


def _claim_sentence(claim: Claim) -> str:
    text = claim.text.strip()
    if text and text[-1] not in ".!?":
        text += "."
    citation = f" [{', '.join(claim.source_ids)}]" if claim.source_ids else ""
    return f"{text}{citation}"


def _question_focus(message: str) -> str:
    normalized = " ".join(message.strip().split()).rstrip("?.")
    return normalized or "the requested topic"


def _important_words(text: str) -> set[str]:
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "retrieved",
        "record",
        "records",
        "includes",
        "include",
        "patient",
        "chart",
        "list",
        "shows",
    }
    return {
        token.strip(".,:;()[]{}'\"").lower()
        for token in text.split()
        if len(token.strip(".,:;()[]{}'\"")) > 3 and token.strip(".,:;()[]{}'\"").lower() not in stop_words
    }
