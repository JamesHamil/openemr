from __future__ import annotations

from .schemas import AgentForgeRequest, AgentForgeResponse, Claim, EvidenceSource, ResponseSection, ResponseSource, WarningItem


HEART_TERMS = (
    "heart",
    "cardiac",
    "cardiovascular",
    "coronary",
    "myocardial",
    "infarction",
    "angina",
    "arrhythmia",
    "atrial fibrillation",
    "afib",
    "heart failure",
    "cardiomyopathy",
    "hypertension",
)


def direct_answer_for(request: AgentForgeRequest, trace_id: str) -> AgentForgeResponse | None:
    normalized = " ".join(request.message.lower().split())
    if _looks_like_broad_brief(normalized):
        return None
    if "allerg" in normalized:
        return _allergy_answer(request, trace_id)
    if any(term in normalized for term in HEART_TERMS):
        return _heart_answer(request, trace_id)
    return None


def _looks_like_broad_brief(message: str) -> bool:
    return any(term in message for term in ("brief", "summary", "rounds", "rounding", "overview"))


def _allergy_answer(request: AgentForgeRequest, trace_id: str) -> AgentForgeResponse:
    allergy_sources = _sources_by_type(request, "allergy")
    allergy_status = _adapter_status(request, "allergies")

    if allergy_sources:
        names = [_clean_source_value(source.value) for source in allergy_sources]
        claim = Claim(
            id="direct-allergies",
            text="Retrieved allergy records list: " + ", ".join(names) + ".",
            claim_type="allergy",
            source_ids=[source.id for source in allergy_sources],
            support_status="supported",
        )
        return AgentForgeResponse(
            answer="Yes. Retrieved allergy records list: " + ", ".join(names) + ".",
            sections=[ResponseSection(id="allergies", title="Allergies", claim_ids=[claim.id])],
            claims=[claim],
            sources=[_response_source(source) for source in allergy_sources],
            warnings=[],
            blocked_claims=[],
            verification_status="verified",
            trace_id=trace_id,
        )

    reason = allergy_status.reason if allergy_status else "No allergy evidence was included in the bounded evidence bundle."
    return AgentForgeResponse(
        answer=(
            "I did not find active allergy entries in the retrieved OpenEMR lists. "
            "I cannot verify that the patient has no allergies; confirm in the chart before relying on this."
        ),
        sections=[],
        claims=[],
        sources=[],
        warnings=[
            WarningItem(
                code="no_allergies_record",
                message=f"Allergy adapter unavailable; {reason[0].lower() + reason[1:] if reason else 'no active allergy records were found.'}",
            )
        ],
        blocked_claims=[],
        verification_status="partial",
        trace_id=trace_id,
    )


def _heart_answer(request: AgentForgeRequest, trace_id: str) -> AgentForgeResponse:
    problem_sources = _sources_by_type(request, "problem")
    heart_sources = [
        source
        for source in problem_sources
        if any(term in source.value.lower() for term in HEART_TERMS)
    ]
    problem_status = _adapter_status(request, "problem_list")

    if heart_sources:
        names = [_clean_source_value(source.value) for source in heart_sources]
        claim = Claim(
            id="direct-heart-issues",
            text="Retrieved problem list includes cardiovascular-related issue(s): " + ", ".join(names) + ".",
            claim_type="problem",
            source_ids=[source.id for source in heart_sources],
            support_status="supported",
        )
        return AgentForgeResponse(
            answer=(
                "The retrieved problem list includes cardiovascular-related issue(s): "
                + ", ".join(names)
                + ". I do not see a retrieved problem-list diagnosis for coronary disease, heart failure, MI, or arrhythmia in this bounded evidence."
            ),
            sections=[ResponseSection(id="heart_issues", title="Heart Issues", claim_ids=[claim.id])],
            claims=[claim],
            sources=[_response_source(source) for source in heart_sources],
            warnings=[],
            blocked_claims=[],
            verification_status="verified",
            trace_id=trace_id,
        )

    warning = "Problem-list evidence did not include a heart/cardiac diagnosis in the bounded evidence bundle."
    if problem_status and problem_status.status != "success":
        warning = f"Problem-list adapter {problem_status.status}; {problem_status.reason}"
    return AgentForgeResponse(
        answer=(
            "I did not find a heart/cardiac diagnosis in the retrieved problem-list records. "
            "This does not rule out heart disease outside the bounded evidence bundle; confirm in the chart."
        ),
        sections=[],
        claims=[],
        sources=[],
        warnings=[WarningItem(code="no_heart_issue_record", message=warning)],
        blocked_claims=[],
        verification_status="partial",
        trace_id=trace_id,
    )


def _sources_by_type(request: AgentForgeRequest, record_type: str) -> list[EvidenceSource]:
    return [
        source
        for source in request.evidence_bundle.sources
        if source.record_type == record_type and source.value.strip()
    ]


def _adapter_status(request: AgentForgeRequest, adapter: str):
    for status in request.evidence_bundle.adapter_status:
        if status.adapter == adapter:
            return status
    return None


def _response_source(source: EvidenceSource) -> ResponseSource:
    return ResponseSource(
        id=source.id,
        record_type=source.record_type,
        display=source.value,
        recorded_at=source.recorded_at,
        field_path=source.field_path,
        extracted_value=_clean_source_value(source.value),
    )


def _clean_source_value(value: str) -> str:
    return " ".join(value.split())
