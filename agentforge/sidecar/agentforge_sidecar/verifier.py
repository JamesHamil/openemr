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
            display = status.adapter.replace("_", " ")
            warnings.append(
                WarningItem(
                    code=f"collector_{status.status}",
                    message=f"{display.title()} data was {status.status} in retrieved OpenEMR records{reason}.",
                )
            )
    return warnings


def verify_response(request: AgentForgeRequest, response: AgentForgeResponse) -> AgentForgeResponse:
    source_by_id = {source.id: source for source in request.evidence_bundle.sources}
    response_source_ids = {source.id for source in response.sources}
    blocked: list[str] = list(response.blocked_claims)
    checked_claims: list[Claim] = []

    for claim in response.claims:
        if claim.support_status != "supported":
            blocked.append(claim.id)
            checked_claims.append(claim.model_copy(update={"support_status": "blocked"}))
            continue

        if not claim.source_ids:
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
        answer = _safe_answer_after_blocking(supported_claims)
        status = "partial"
    if warnings and status == "verified":
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


def _safe_answer_after_blocking(claims: list[Claim]) -> str:
    if not claims:
        return "Clinical Co-Pilot could not verify the generated clinical claims against the retrieved chart evidence."

    lines = ["Clinical Co-Pilot removed unsupported generated claims. Verified chart facts:"]
    for claim in claims[:6]:
        citation = f" [{', '.join(claim.source_ids)}]" if claim.source_ids else ""
        lines.append(f"- {claim.text}{citation}")
    return "\n".join(lines)


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
