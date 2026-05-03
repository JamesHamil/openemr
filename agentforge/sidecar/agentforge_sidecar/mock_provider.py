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
            metadata=source.metadata,
        )
        for source in request.evidence_bundle.sources[:10]
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
            answer=_natural_answer(request.message, response_sources, request.evidence_bundle.adapter_status),
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

    return AgentForgeResponse(
        answer=_natural_answer(request.message, response_sources, request.evidence_bundle.adapter_status),
        sections=sections,
        claims=claims,
        sources=response_sources,
        warnings=[],
        blocked_claims=[],
        verification_status="verified",
        trace_id=trace_id,
    )


def _natural_answer(message: str, sources: list[ResponseSource], adapter_status) -> str:
    normalized = message.lower().strip()
    by_type = _group_sources(sources)
    problems = by_type.get("problem", [])
    allergies = by_type.get("allergy", [])
    positive_allergies = allergies
    meds = by_type.get("medication", [])
    labs = by_type.get("lab", [])
    notes = by_type.get("note", [])
    missing = [status.adapter for status in adapter_status if status.status != "success"]

    if "medication reconciliation" in normalized or "reconciliation" in normalized:
        if meds:
            return (
                f"Medication reconciliation summary: current listed meds include {_join_values(meds)}. "
                "Confirm active medications versus historical entries before ordering changes."
            )
        return "No active medication entries were retrieved for reconciliation in this snapshot."

    if "what changed" in normalized or "changed since" in normalized or "since last review" in normalized:
        if notes:
            return f"Recent notes show a change to verify: {_join_values(notes)}."
        return "No recent note evidence was retrieved to compare changes since last review; confirm in the chart."

    if _is_broad_brief_request(normalized):
        sentences = []
        if problems:
            sentences.append(f"Problem list includes {_join_values(problems)}.")
        if positive_allergies:
            sentences.append(f"Allergies include {_join_values(positive_allergies)}.")
        else:
            sentences.append("No active allergy records were found in this retrieved snapshot.")
        if meds:
            sentences.append(f"Current listed meds include {_join_values(meds)}.")
        if missing:
            sentences.append(
                f"Key follow-up: confirm missing {', '.join(adapter.replace('_', ' ') for adapter in missing[:3])} in the chart."
            )
        return " ".join(sentences[:5])

    if "allerg" in normalized:
        if positive_allergies:
            response = f"Documented allergies: {_join_values(positive_allergies)}."
        else:
            response = "No active allergy records were found in the retrieved snapshot."
        if any("epinephrine" in source.extracted_value.lower() for source in meds):
            response += " Epinephrine auto-injector appears on the medication list; confirm reaction severity and trigger history."
        return response

    if "cardiac" in normalized or "heart" in normalized:
        cardiac_terms = ("cardiac", "heart", "arrhythm", "cad", "chf", "mi", "angina", "hypertension")
        cardiac_problems = [source for source in problems if any(term in source.extracted_value.lower() for term in cardiac_terms)]
        if cardiac_problems:
            return f"Active chart issues include {_join_values(cardiac_problems)}. Confirm with recent vitals and notes before final assessment."
        return "No explicit heart/cardiac diagnosis was found in the retrieved problem-list records; confirm in the chart."

    if "endocrine" in normalized or "metabolic" in normalized:
        metabolic_terms = ("prediabetes", "diabetes", "hyperlipid", "dyslipid")
        metabolic_problems = [source for source in problems if any(term in source.extracted_value.lower() for term in metabolic_terms)]
        if metabolic_problems:
            return f"{_join_values(metabolic_problems).capitalize()} are present on the problem list, suggesting cardiometabolic risk. Review recent labs for current trend."
        return "I did not find endocrine/metabolic diagnoses in the retrieved records; confirm with problem list and labs."

    if "oncolog" in normalized or "cancer" in normalized or "neoplasm" in normalized:
        oncology_terms = ("cancer", "neoplasm", "malignant", "carcinoma")
        oncology_problems = [source for source in problems if any(term in source.extracted_value.lower() for term in oncology_terms)]
        if oncology_problems:
            return f"Yes. Problem list includes {_join_values(oncology_problems)}. Confirm active-vs-history status and current oncology follow-up."
        return "No oncology diagnosis was found in the retrieved problem list; confirm with full chart history."

    if "red flag" in normalized or "inconsisten" in normalized or "verify" in normalized:
        potential_flags = [
            source for source in problems if any(term in source.extracted_value.lower() for term in ("bullet", "miscarriage"))
        ]
        if potential_flags:
            return (
                f"Potential chart red flags to verify include {_join_values(potential_flags)}. "
                "Confirm whether these are active issues versus historical entries."
            )
        return "No obvious record inconsistencies were identified in this retrieved snapshot; confirm active-vs-history status in the chart."

    if "ask the patient first" in normalized or "enter the room" in normalized:
        return (
            "Start by confirming the patient's top symptoms today, then review allergy reaction history, "
            "current medication use, and whether major problem-list diagnoses are still active."
        )

    if "missing" in normalized:
        if missing:
            return f"Missing or unavailable retrieved data includes {', '.join(adapter.replace('_', ' ') for adapter in missing[:4])}; confirm in chart before final decisions."
        return "Retrieved evidence appears complete for this bundle, but clinical decisions should still be confirmed in full chart context."

    return _focused_uncertainty_answer(message)


def _is_broad_brief_request(normalized_message: str) -> bool:
    return any(
        phrase in normalized_message
        for phrase in ("chart brief", "pre-round", "rounds", "one-minute")
    )


def _group_sources(sources: list[ResponseSource]) -> dict[str, list[ResponseSource]]:
    grouped: dict[str, list[ResponseSource]] = {}
    for source in sources:
        grouped.setdefault(source.record_type, []).append(source)
    return grouped


def _join_values(items: list[ResponseSource], limit: int = 6) -> str:
    values = []
    for source in items:
        text = source.extracted_value.strip()
        if not text:
            continue
        values.append(text)
        if len(values) >= limit:
            break
    if not values:
        return "no retrieved entries"
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _focused_uncertainty_answer(message: str) -> str:
    normalized = " ".join(message.strip().split()).rstrip("?.")
    focus = normalized or "the requested topic"
    return f'I did not find retrieved evidence for "{focus}" in the bounded records; confirm in the chart.'
