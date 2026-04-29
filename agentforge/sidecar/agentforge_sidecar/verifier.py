from __future__ import annotations

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
            warnings.append(
                WarningItem(
                    code=f"collector_{status.status}",
                    message=f"{status.adapter} collector reported {status.status}{reason}.",
                )
            )
    return warnings


def verify_response(request: AgentForgeRequest, response: AgentForgeResponse) -> AgentForgeResponse:
    source_by_id = {source.id: source for source in request.evidence_bundle.sources}
    response_source_ids = {source.id for source in response.sources}
    blocked: list[str] = list(response.blocked_claims)
    verified_claims: list[Claim] = []

    for claim in response.claims:
        if claim.support_status != "supported":
            blocked.append(claim.id)
            verified_claims.append(claim.model_copy(update={"support_status": "blocked"}))
            continue

        if not claim.source_ids:
            blocked.append(claim.id)
            verified_claims.append(claim.model_copy(update={"support_status": "blocked"}))
            continue

        missing_sources = [
            source_id
            for source_id in claim.source_ids
            if source_id not in source_by_id or source_id not in response_source_ids
        ]
        if missing_sources:
            blocked.append(claim.id)
            verified_claims.append(claim.model_copy(update={"support_status": "blocked"}))
            continue

        if not _claim_has_source_overlap(claim, [source_by_id[source_id].value for source_id in claim.source_ids]):
            blocked.append(claim.id)
            verified_claims.append(claim.model_copy(update={"support_status": "blocked"}))
            continue

        verified_claims.append(claim)

    warnings = response.warnings + adapter_warnings(request)
    for source in request.evidence_bundle.sources:
        if has_prompt_injection_text(source.value) or (source.note_span and has_prompt_injection_text(source.note_span)):
            warnings.append(
                WarningItem(
                    code="prompt_injection_in_chart_text",
                    message="Retrieved chart text contained instruction-like content and was treated only as patient-record evidence.",
                )
            )
            break

    status: ResponseStatus = response.verification_status
    if blocked:
        status = "partial" if verified_claims else "failed"
    if warnings and status == "verified":
        status = "partial"

    return response.model_copy(
        update={
            "claims": verified_claims,
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
