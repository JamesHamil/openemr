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
Return strict structured facts with citations. For PDF/image inputs, include page-relative
bounding boxes when visible; otherwise leave bounding_box null and preserve page/section plus quote_or_value.
Use low confidence and warnings for uncertain, missing, or unreadable fields."""


class ModelExtractionResult(StrictModel):
    extraction_status: Literal["success", "partial", "failed"]
    extracted_facts: list[ExtractedFact] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)


def extract_document(
    request: DocumentExtractionRequest,
    settings: Settings,
) -> tuple[DocumentExtractionResponse, dict]:
    started = time.perf_counter()
    trace_id = f"af-doc-{uuid.uuid4()}"
    if settings.mode == "off":
        return _failed_response(
            request,
            trace_id,
            "agentforge_off",
            "The sidecar is configured in off mode.",
            started,
        )

    if settings.mode == "real":
        try:
            response, diagnostics = _real_extract(request, settings, trace_id, started)
            return response, diagnostics
        except Exception as exc:
            fallback, diagnostics = _heuristic_extract(request, trace_id, started)
            fallback.warnings.append(
                WarningItem(
                    code="real_extraction_fallback",
                    message=f"Real extraction failed; heuristic extraction was used for demo continuity: {exc}",
                )
            )
            fallback = fallback.model_copy(update={"extraction_status": "partial"})
            diagnostics["fallback_reason"] = "real_extraction_fallback"
            return fallback, diagnostics

    return _heuristic_extract(request, trace_id, started)


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
        max_output_tokens=2200,
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
    facts = _heuristic_lab_facts(request, text) if request.document_type == "lab_pdf" else _heuristic_intake_facts(request, text)
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
            page_or_section="page 1" if request.document_type == "lab_pdf" else "intake form",
            field_or_chunk_id=f"{fact_type}-{index + 1}",
            quote_or_value=quote,
            bounding_box=None,
        ),
    )


def _normalize_fact(request: DocumentExtractionRequest, fact: ExtractedFact, index: int) -> ExtractedFact:
    citation = fact.citation.model_copy(
        update={
            "source_type": fact.citation.source_type or request.document_type,
            "source_id": fact.citation.source_id or request.source_id,
            "field_or_chunk_id": fact.citation.field_or_chunk_id or f"{fact.fact_type}-{index + 1}",
            "quote_or_value": fact.citation.quote_or_value or fact.value,
        }
    )
    return fact.model_copy(update={"citation": citation})


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
