from __future__ import annotations

import base64
import json
import re
import time
import uuid
from typing import Literal

from pydantic import Field

from .schemas import (
    DocumentExtractionRequest,
    DocumentExtractionResponse,
    ExtractedFact,
    SourceCitation,
    StrictModel,
    WarningItem,
    WorkerHandoff,
)
from .settings import Settings
from .tool_agent import _usage_tokens


EXTRACTION_PROMPT = """You are AgentForge's clinical document extraction worker.
Extract only facts visible in the provided document. Do not infer missing facts.
Return strict structured facts with citations. For PDF/image inputs, include normalized page-relative
bounding boxes only when the exact source region is visually identifiable. Use x, y, width, and height
values from 0.0 to 1.0, plus an optional integer page. Otherwise leave bounding_box null and preserve
page/section plus quote_or_value.
For medication_list documents, extract each visible medication as a separate medication fact when possible,
including name, dose, route, frequency, status, prescriber, and start/stop dates only when visible.
Use low confidence and warnings for uncertain, missing, or unreadable fields."""

CANONICAL_FIELD_LABELS = {
    "phone": "Patient Phone",
    "patient_phone": "Patient Phone",
    "emergency_contact_phone": "Emergency Contact Phone",
    "pharmacy_phone": "Pharmacy Phone",
    "address": "Patient Address",
    "pharmacy_address": "Pharmacy Address",
}


class ModelExtractionResult(StrictModel):
    extraction_status: Literal["success", "partial", "failed"]
    extracted_facts: list[ExtractedFact] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)


def extract_document(
    request: DocumentExtractionRequest,
    settings: Settings,
) -> tuple[DocumentExtractionResponse, dict]:
    from .supervisor_graph import run_document_extraction_graph

    started = time.perf_counter()
    trace_id = f"af-doc-{uuid.uuid4()}"
    result = run_document_extraction_graph(
        request=request,
        settings=settings,
        trace_id=trace_id,
        started=started,
        real_extract=_real_extract,
        heuristic_extract=_heuristic_extract,
        failed_response=_failed_response,
    )
    return result.response, result.diagnostics


def _real_extract(
    request: DocumentExtractionRequest,
    settings: Settings,
    trace_id: str,
    started: float,
) -> tuple[DocumentExtractionResponse, dict]:
    from openai import OpenAI

    client = OpenAI()
    data_url = f"data:{request.mime_type};base64,{request.content_base64}"
    user_text = (
        f"Document type: {request.document_type}\n"
        f"Source id: {request.source_id}\n"
        f"Filename: {request.filename}\n"
        "Extract facts required by the AgentForge schema."
    )
    content = [{"type": "input_text", "text": user_text}]
    if request.mime_type == "application/pdf":
        content.append({"type": "input_file", "filename": request.filename, "file_data": data_url})
    elif request.mime_type.startswith("image/"):
        content.append({"type": "input_image", "image_url": data_url})
    else:
        content.append(
            {
                "type": "input_text",
                "text": _decode_text_hint(request) or request.text_hint or "No text preview was available.",
            }
        )

    parsed_response = client.responses.parse(
        model=settings.model,
        reasoning=settings.reasoning,
        max_output_tokens=10000,
        input=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": content},
        ],
        text_format=ModelExtractionResult,
    )
    parsed = parsed_response.output_parsed
    if not parsed:
        raise RuntimeError("Document extraction did not return parsed output")

    input_tokens, output_tokens = _usage_tokens(parsed_response)
    facts = [_normalize_fact(request, fact, index) for index, fact in enumerate(parsed.extracted_facts)]
    handoff = _handoff(
        request=request,
        started=started,
        status=parsed.extraction_status,
        reason="Document required model-based extraction.",
        selected=[fact.citation.field_or_chunk_id for fact in facts],
    )
    response = DocumentExtractionResponse(
        document_type=request.document_type,
        extraction_status=parsed.extraction_status,
        extracted_facts=facts,
        warnings=parsed.warnings,
        worker_handoffs=[handoff],
        trace_id=trace_id,
    )
    return response, {
        "trace_id": trace_id,
        "latency_ms": handoff.latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "mode": settings.mode,
    }


def _heuristic_extract(
    request: DocumentExtractionRequest,
    trace_id: str,
    started: float,
) -> tuple[DocumentExtractionResponse, dict]:
    text = _decode_text_hint(request) or request.text_hint or request.filename
    if request.document_type == "lab_pdf":
        facts = _heuristic_lab_facts(request, text)
    elif request.document_type == "medication_list":
        facts = _heuristic_medication_list_facts(request, text)
    else:
        facts = _heuristic_intake_facts(request, text)
    warnings = []
    if not facts:
        warnings.append(
            WarningItem(
                code="no_extractable_facts",
                message="No structured facts were confidently extracted from the uploaded document snapshot.",
            )
        )
    status = "success" if facts else "partial"
    handoff = _handoff(
        request=request,
        started=started,
        status=status,
        reason="Document routed to deterministic extraction worker.",
        selected=[fact.citation.field_or_chunk_id for fact in facts],
    )
    return (
        DocumentExtractionResponse(
            document_type=request.document_type,
            extraction_status=status,
            extracted_facts=facts,
            warnings=warnings,
            worker_handoffs=[handoff],
            trace_id=trace_id,
        ),
        {
            "trace_id": trace_id,
            "latency_ms": handoff.latency_ms,
            "input_tokens": 0,
            "output_tokens": 0,
            "mode": "mock",
        },
    )


def _heuristic_lab_facts(request: DocumentExtractionRequest, text: str) -> list[ExtractedFact]:
    facts = []
    patterns = [
        ("potassium", r"\bpotassium\b[^\d-]*(\d+(?:\.\d+)?)\s*([a-zA-Z/%]+)?", "mmol/L"),
        ("glucose", r"\bglucose\b[^\d-]*(\d+(?:\.\d+)?)\s*([a-zA-Z/%]+)?", "mg/dL"),
        ("a1c", r"\b(?:a1c|hba1c)\b[^\d-]*(\d+(?:\.\d+)?)\s*(%)?", "%"),
        ("creatinine", r"\bcreatinine\b[^\d-]*(\d+(?:\.\d+)?)\s*([a-zA-Z/%]+)?", "mg/dL"),
    ]
    lower = text.lower()
    for label, pattern, default_unit in patterns:
        match = re.search(pattern, lower, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1)
        unit = match.group(2) or default_unit
        abnormal = "high" if _looks_abnormal(label, value) else ""
        facts.append(
            _fact(
                request=request,
                fact_type="lab_result",
                label=label.title() if label != "a1c" else "A1c",
                value=value,
                unit=unit,
                abnormal_flag=abnormal,
                quote=f"{label} {value} {unit}".strip(),
                index=len(facts),
            )
        )
    if not facts and request.document_type == "lab_pdf":
        facts.append(
            _fact(
                request=request,
                fact_type="lab_document",
                label="Uploaded lab PDF",
                value="Lab PDF uploaded for clinician review",
                unit="",
                abnormal_flag="",
                quote=request.filename,
                index=0,
                confidence=0.55,
            )
        )
    return facts


def _heuristic_intake_facts(request: DocumentExtractionRequest, text: str) -> list[ExtractedFact]:
    facts = []
    fields = {
        "chief_concern": r"(?:chief concern|reason for visit|concern)[:\s-]+([^\n\r;]+)",
        "current_medications": r"(?:current medications|medications|meds)[:\s-]+([^\n\r;]+)",
        "allergies": r"(?:allergies|allergy)[:\s-]+([^\n\r;]+)",
        "family_history": r"(?:family history)[:\s-]+([^\n\r;]+)",
    }
    for fact_type, pattern in fields.items():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip()
        facts.append(
            _fact(
                request=request,
                fact_type=fact_type,
                label=fact_type.replace("_", " ").title(),
                value=value,
                unit="",
                abnormal_flag="",
                quote=value,
                index=len(facts),
            )
        )
    if not facts and request.document_type == "intake_form":
        facts.append(
            _fact(
                request=request,
                fact_type="intake_document",
                label="Uploaded intake form",
                value="Intake form uploaded for clinician review",
                unit="",
                abnormal_flag="",
                quote=request.filename,
                index=0,
                confidence=0.55,
            )
        )
    return facts


def _heuristic_medication_list_facts(request: DocumentExtractionRequest, text: str) -> list[ExtractedFact]:
    facts = []
    medication_names = (
        "albuterol",
        "amlodipine",
        "aspirin",
        "atorvastatin",
        "cetirizine",
        "epinephrine",
        "gabapentin",
        "hydrochlorothiazide",
        "insulin",
        "levothyroxine",
        "lisinopril",
        "loratadine",
        "metformin",
        "omeprazole",
        "prednisone",
        "simvastatin",
    )
    dose_pattern = re.compile(
        r"^\s*(?:[-*]\s*)?(?P<name>[A-Za-z][A-Za-z0-9 /-]{1,60}?)\s+"
        r"(?P<dose>\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|mL|units?|iu|IU|%|tablet|tab|capsule|cap|puff)s?)\b"
        r"(?P<rest>[^\n\r]*)",
        flags=re.IGNORECASE,
    )

    for raw_line in re.split(r"[\n\r;]+", text):
        line = raw_line.strip(" \t-*")
        if not line:
            continue
        lower = line.lower()
        match = dose_pattern.search(line)
        has_known_name = any(name in lower for name in medication_names)
        if not match and not (has_known_name and re.search(r"\d", line)):
            continue

        label = _medication_label_from_line(line, match, medication_names)
        if not label:
            continue
        facts.append(
            _fact(
                request=request,
                fact_type="medication",
                label=label,
                value=line,
                unit="",
                abnormal_flag="",
                quote=line,
                index=len(facts),
                confidence=0.72 if match else 0.62,
            )
        )
        if len(facts) >= 24:
            break

    if not facts and request.document_type == "medication_list":
        facts.append(
            _fact(
                request=request,
                fact_type="medication_document",
                label="Uploaded medication list",
                value="Medication list uploaded for clinician review",
                unit="",
                abnormal_flag="",
                quote=request.filename,
                index=0,
                confidence=0.55,
            )
        )
    return facts


def _medication_label_from_line(line: str, match: re.Match | None, medication_names: tuple[str, ...]) -> str:
    if match:
        raw_name = re.sub(r"\b(?:active|current|medication|medications)\b", "", match.group("name"), flags=re.IGNORECASE)
        raw_name = re.sub(r"\s+", " ", raw_name).strip(" :-")
        if raw_name:
            return raw_name.title()
    lower = line.lower()
    for name in medication_names:
        if name in lower:
            return name.title()
    return ""


def _fact(
    request: DocumentExtractionRequest,
    fact_type: str,
    label: str,
    value: str,
    unit: str,
    abnormal_flag: str,
    quote: str,
    index: int,
    confidence: float = 0.82,
) -> ExtractedFact:
    return ExtractedFact(
        fact_type=fact_type,
        label=label,
        value=value,
        unit=unit,
        abnormal_flag=abnormal_flag,
        confidence=confidence,
        citation=SourceCitation(
            source_type=request.document_type,
            source_id=request.source_id,
            page_or_section=_default_page_or_section(request.document_type),
            field_or_chunk_id=f"{fact_type}-{index + 1}",
            quote_or_value=quote,
            bounding_box=None,
        ),
    )


def _default_page_or_section(document_type: str) -> str:
    if document_type == "lab_pdf":
        return "page 1"
    if document_type == "medication_list":
        return "medication list"
    return "intake form"


def _normalize_fact(request: DocumentExtractionRequest, fact: ExtractedFact, index: int) -> ExtractedFact:
    page_or_section = fact.citation.page_or_section or _default_page_or_section(request.document_type)
    bounding_box = _normalize_bounding_box(fact.citation.bounding_box, page_or_section)
    if bounding_box is None:
        bounding_box = _fallback_bounding_box(request, fact, index)
    citation = fact.citation.model_copy(
        update={
            "source_type": fact.citation.source_type or request.document_type,
            "source_id": fact.citation.source_id or request.source_id,
            "page_or_section": page_or_section,
            "field_or_chunk_id": fact.citation.field_or_chunk_id or f"{fact.fact_type}-{index + 1}",
            "quote_or_value": fact.citation.quote_or_value or fact.value,
            "bounding_box": bounding_box,
        }
    )
    label = CANONICAL_FIELD_LABELS.get(citation.field_or_chunk_id.strip().lower(), fact.label)
    return fact.model_copy(update={"citation": citation, "label": label})


def _fallback_bounding_box(
    request: DocumentExtractionRequest,
    fact: ExtractedFact,
    index: int,
) -> dict[str, float | int] | None:
    if request.document_type != "medication_list" or not request.mime_type.startswith("image/"):
        return None
    if fact.fact_type not in {"medication", "medication_document"}:
        return None
    y = min(0.9, 0.17 + (index * 0.046))
    return {"x": 0.06, "y": y, "width": 0.88, "height": 0.042, "page": 1}


def _normalize_bounding_box(box: dict[str, float | int] | None, page_or_section: str = "") -> dict[str, float | int] | None:
    if not isinstance(box, dict):
        return None

    normalized: dict[str, float | int] = {}
    for key in ("x", "y", "width", "height"):
        value = _float_or_none(box.get(key))
        if value is None:
            return None
        normalized[key] = _clamp01(value)

    x = float(normalized["x"])
    y = float(normalized["y"])
    width = min(float(normalized["width"]), 1.0 - x)
    height = min(float(normalized["height"]), 1.0 - y)
    if width <= 0 or height <= 0:
        return None

    normalized["width"] = width
    normalized["height"] = height
    page = _page_number(box.get("page"), page_or_section)
    if page is not None:
        normalized["page"] = page
    return normalized


def _float_or_none(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _clamp01(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _page_number(raw_page, page_or_section: str) -> int | None:
    try:
        page = int(raw_page)
        if page > 0:
            return page
    except (TypeError, ValueError):
        pass

    match = re.search(r"\bpage\s+(\d+)\b", page_or_section, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _handoff(
    request: DocumentExtractionRequest,
    started: float,
    status: str,
    reason: str,
    selected: list[str],
) -> WorkerHandoff:
    return WorkerHandoff(
        worker="intake-extractor",
        route_reason=reason,
        input_summary=f"{request.document_type} {request.filename}",
        output_status=status,
        latency_ms=int((time.perf_counter() - started) * 1000),
        selected_citation_ids=selected,
    )


def _failed_response(
    request: DocumentExtractionRequest,
    trace_id: str,
    code: str,
    message: str,
    started: float,
) -> tuple[DocumentExtractionResponse, dict]:
    handoff = _handoff(request, started, "failed", message, [])
    return (
        DocumentExtractionResponse(
            document_type=request.document_type,
            extraction_status="failed",
            warnings=[WarningItem(code=code, message=message)],
            worker_handoffs=[handoff],
            trace_id=trace_id,
        ),
        {"trace_id": trace_id, "latency_ms": handoff.latency_ms, "error": message},
    )


def _decode_text_hint(request: DocumentExtractionRequest) -> str:
    try:
        decoded = base64.b64decode(request.content_base64).decode("utf-8", errors="ignore")[:8000]
    except Exception:
        decoded = ""
    if request.mime_type.startswith("text/"):
        return decoded or request.text_hint
    return request.text_hint or decoded


def _looks_abnormal(label: str, value: str) -> bool:
    try:
        number = float(value)
    except ValueError:
        return False
    return (label == "potassium" and number >= 5.2) or (label == "glucose" and number >= 180) or (label == "a1c" and number >= 6.5)
