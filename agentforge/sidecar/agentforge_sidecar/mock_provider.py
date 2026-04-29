from __future__ import annotations

from .schemas import (
    AgentForgeRequest,
    AgentForgeResponse,
    Claim,
    ResponseSection,
    ResponseSource,
    WarningItem,
)
from .verifier import is_treatment_directive


def mock_response(request: AgentForgeRequest, trace_id: str) -> AgentForgeResponse:
    if any(status.adapter == "authorization" and status.status == "failed" for status in request.evidence_bundle.adapter_status):
        return AgentForgeResponse(
            answer="I cannot answer for an unauthorized patient context.",
            sections=[],
            claims=[],
            sources=[],
            warnings=[
                WarningItem(
                    code="unauthorized_patient_refused",
                    message="OpenEMR did not authorize this patient context.",
                )
            ],
            blocked_claims=[],
            verification_status="refused",
            trace_id=trace_id,
        )

    if is_treatment_directive(request.message):
        return AgentForgeResponse(
            answer=(
                "I cannot provide treatment directives. I can summarize retrieved chart evidence "
                "for physician review."
            ),
            sections=[],
            claims=[],
            sources=[],
            warnings=[
                WarningItem(
                    code="treatment_directive_refused",
                    message="The request asked for a treatment action and was reframed for physician review.",
                )
            ],
            blocked_claims=[],
            verification_status="refused",
            trace_id=trace_id,
        )

    response_sources = [
        ResponseSource(
            id=source.id,
            record_type=source.record_type,
            display=f"{source.record_type.title()} source",
            recorded_at=source.recorded_at,
            field_path=source.field_path,
            extracted_value=source.value,
        )
        for source in request.evidence_bundle.sources[:8]
    ]

    claims: list[Claim] = []
    sections_by_type: dict[str, list[str]] = {}
    for index, source in enumerate(response_sources, start=1):
        claim_id = f"claim-{index:03d}"
        claims.append(
            Claim(
                id=claim_id,
                text=f"The retrieved {source.record_type} source includes {source.extracted_value}.",
                claim_type=source.record_type,
                source_ids=[source.id],
                support_status="supported",
            )
        )
        sections_by_type.setdefault(source.record_type, []).append(claim_id)

    sections = [
        ResponseSection(id=record_type, title=record_type.replace("_", " ").title(), claim_ids=claim_ids)
        for record_type, claim_ids in sections_by_type.items()
    ]

    if not claims:
        return AgentForgeResponse(
            answer="I could not find supported facts in the retrieved evidence bundle.",
            sections=[],
            claims=[],
            sources=[],
            warnings=[
                WarningItem(
                    code="empty_evidence_bundle",
                    message="OpenEMR supplied no source records in this evidence bundle.",
                )
            ],
            blocked_claims=[],
            verification_status="partial",
            trace_id=trace_id,
        )

    answer_lines = [
        "Here is a source-backed chart brief from the retrieved OpenEMR evidence.",
        "",
    ]
    for claim in claims[:6]:
        answer_lines.append(f"- {claim.text} [{', '.join(claim.source_ids)}]")

    return AgentForgeResponse(
        answer="\n".join(answer_lines),
        sections=sections,
        claims=claims,
        sources=response_sources,
        warnings=[],
        blocked_claims=[],
        verification_status="verified",
        trace_id=trace_id,
    )
