from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .schemas import AgentForgeRequest, EvidenceSource, ToolCallResult, ToolName, ToolPhaseResult

MAX_TOOL_CALLS = 6
FALLBACK_RECORD_TYPE_ORDER = ["problem", "allergy", "medication", "lab", "document_fact", "guideline", "vital", "note", "demographic"]
LAB_DOCUMENT_FACT_HINTS = {
    "a1c",
    "blast",
    "blood count",
    "bun",
    "cbc",
    "chloride",
    "creatinine",
    "differential",
    "eosinophil",
    "erythrocyte",
    "glucose",
    "hematocrit",
    "hemoglobin",
    "leukocyte",
    "lymphocyte",
    "mcv",
    "metamyelocyte",
    "monocyte",
    "neutrophil",
    "platelet",
    "potassium",
    "promyelocyte",
    "sodium",
    "wbc",
}
DOCUMENT_FACT_FIELD_GROUPS = {
    "phone_numbers": {"phone", "patient_phone", "emergency_contact_phone", "pharmacy_phone"},
    "intake_contact": {"phone", "patient_phone", "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relationship"},
    "pharmacy": {"preferred_pharmacy_name", "pharmacy_phone", "pharmacy_address"},
    "insurance": {"insurance_provider", "provider", "policy_number", "group_number", "policyholder_name"},
    "medication_list": {"medication", "medication_name", "dose", "dosage", "frequency", "route", "prescriber"},
    "labs": set(LAB_DOCUMENT_FACT_HINTS),
}
SEMANTIC_TYPE_HINTS = {
    "problem": {
        "problem",
        "problems",
        "issue",
        "issues",
        "condition",
        "conditions",
        "diagnosis",
        "diagnoses",
        "major",
        "active",
    },
    "allergy": {"allergy", "allergies", "reaction", "reactions"},
    "medication": {"medication", "medications", "med", "meds", "drug", "drugs", "reconcile", "reconciliation"},
    "lab": {"lab", "labs", "result", "results", "glucose", "creatinine", "a1c", "cbc", "hemoglobin", "platelet"},
    "vital": {"vital", "vitals", "blood", "pressure", "pulse", "temperature", "weight"},
    "note": {"note", "notes", "assessment", "plan", "history"},
    "document_fact": {
        "document",
        "pdf",
        "form",
        "intake",
        "uploaded",
        "extracted",
        "phone",
        "phones",
        "number",
        "numbers",
        "contact",
        "emergency",
        "pharmacy",
        "email",
        "address",
        "demographic",
        "medication",
        "medications",
        "med",
        "meds",
        "dose",
    },
    "guideline": {"guideline", "recommend", "follow", "review", "risk", "red", "flag"},
}

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "search_sources",
        "description": "Find relevant evidence sources for a user question.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "record_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional record_type filter like problem, allergy, medication, lab, vital, note, demographic.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_sources",
        "description": "Fetch exact source records by source ids.",
        "parameters": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["ids"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_document_facts",
        "description": "Fetch extracted document facts by document type, field names, or schema field group.",
        "parameters": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "description": "Optional document type filter like intake_form, lab_pdf, or medication_list.",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional citation field ids like phone, emergency_contact_phone, pharmacy_phone.",
                },
                "field_group": {
                    "type": "string",
                    "description": "Optional group: phone_numbers, intake_contact, pharmacy, insurance, medication_list, labs.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "list_adapter_status",
        "description": "Read collector adapter statuses and reasons from OpenEMR evidence collection.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "summarize_by_type",
        "description": "Summarize available evidence counts and representative source ids by record type.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional record_type list like problem, allergy, medication, lab, vital, note, demographic.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "check_allergy_conflicts",
        "description": "Compare allergy and medication evidence for obvious allergy/medication conflicts or allergy-management meds to verify.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]

TOOL_SYSTEM_PROMPT = """You are selecting chart evidence for a hospitalist-facing answer.
You must use tools to inspect evidence and then pick only the most relevant source ids.
Do not invent source ids. Do not infer facts without tool-backed evidence.
Choose concise, question-specific evidence and avoid unrelated chart inventory.
For all/list/show questions about extracted intake or document fields, use get_document_facts
so every matching field is available before selecting source ids."""

TOOL_BUDGET_EXHAUSTED_PROMPT = (
    "Tool-call budget has been reached for this request. "
    "Do not call tools again. Finalize evidence selection from available tool outputs only."
)


@dataclass(frozen=True)
class ToolPhaseDiagnostics:
    tool_call_count: int = 0
    selected_source_count: int = 0
    fallback_reason: str = ""
    planning_latency_ms: int = 0
    invalid_source_id_count: int = 0
    model_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def run_tool_phase(
    client,
    request: AgentForgeRequest,
    model: str,
    reasoning: dict[str, str] | None = None,
) -> tuple[ToolPhaseResult, ToolPhaseDiagnostics]:
    started = time.perf_counter()
    source_by_id = {source.id: source for source in request.evidence_bundle.sources}
    tool_call_count = 0
    model_call_count = 1
    fallback_reason = ""

    summary = _bundle_summary(request)
    response = client.responses.create(
        model=model,
        reasoning=reasoning,
        max_output_tokens=1000,
        input=[
            {"role": "system", "content": TOOL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Question:\n"
                    f"{request.message}\n\n"
                    "Available evidence summary:\n"
                    f"{summary}\n\n"
                    "Use tools to inspect evidence and gather candidate source ids."
                ),
            },
        ],
        tools=TOOL_DEFINITIONS,
    )
    input_tokens, output_tokens = _usage_tokens(response)

    for _ in range(MAX_TOOL_CALLS):
        function_calls = _extract_function_calls(response)
        if not function_calls:
            break

        tool_outputs = []
        budget_exhausted = False
        for call in function_calls:
            if tool_call_count >= MAX_TOOL_CALLS:
                fallback_reason = fallback_reason or "tool_call_limit_reached"
                budget_exhausted = True
                result = ToolCallResult(
                    tool=_tool_literal(call["name"]),
                    success=False,
                    payload={},
                    error="tool_call_limit_reached",
                )
            else:
                tool_call_count += 1
                result = execute_tool(request, call["name"], call["arguments"])
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": json.dumps(result.model_dump(), separators=(",", ":")),
                }
            )
        if not tool_outputs:
            break

        response = client.responses.create(
            model=model,
            reasoning=reasoning,
            previous_response_id=response.id,
            max_output_tokens=1000,
            input=tool_outputs,
            tools=TOOL_DEFINITIONS,
        )
        model_call_count += 1
        next_input_tokens, next_output_tokens = _usage_tokens(response)
        input_tokens += next_input_tokens
        output_tokens += next_output_tokens

        if budget_exhausted:
            response = client.responses.create(
                model=model,
                reasoning=reasoning,
                previous_response_id=response.id,
                max_output_tokens=700,
                input=[{"role": "user", "content": TOOL_BUDGET_EXHAUSTED_PROMPT}],
            )
            model_call_count += 1
            next_input_tokens, next_output_tokens = _usage_tokens(response)
            input_tokens += next_input_tokens
            output_tokens += next_output_tokens
            break

    plan_response = client.responses.parse(
        model=model,
        reasoning=reasoning,
        previous_response_id=response.id,
        max_output_tokens=700,
        input=[
            {
                "role": "user",
                "content": (
                    "Return a ToolPhaseResult JSON object now. "
                    "Select only source ids that directly support answering the question."
                ),
            }
        ],
        text_format=ToolPhaseResult,
    )
    model_call_count += 1
    next_input_tokens, next_output_tokens = _usage_tokens(plan_response)
    input_tokens += next_input_tokens
    output_tokens += next_output_tokens
    parsed = plan_response.output_parsed
    if not parsed:
        raise RuntimeError("Tool phase did not return parsed ToolPhaseResult output")

    selected_source_ids: list[str] = []
    invalid_source_id_count = 0
    for source_id in parsed.selected_source_ids:
        if source_id not in source_by_id:
            invalid_source_id_count += 1
            continue
        if source_id in selected_source_ids:
            continue
        selected_source_ids.append(source_id)

    if invalid_source_id_count > 0:
        fallback_reason = fallback_reason or "invalid_tool_source_ids_removed"

    result = parsed.model_copy(update={"selected_source_ids": selected_source_ids})
    diagnostics = ToolPhaseDiagnostics(
        tool_call_count=tool_call_count,
        selected_source_count=len(selected_source_ids),
        fallback_reason=fallback_reason,
        planning_latency_ms=int((time.perf_counter() - started) * 1000),
        invalid_source_id_count=invalid_source_id_count,
        model_call_count=model_call_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return result, diagnostics


def execute_tool(request: AgentForgeRequest, name: str, arguments_json: str) -> ToolCallResult:
    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return ToolCallResult(tool=_tool_literal(name), success=False, payload={}, error="invalid_json_arguments")

    if name == "search_sources":
        query = str(arguments.get("query", "")).strip()
        record_types = arguments.get("record_types") or []
        if not isinstance(record_types, list):
            record_types = []
        payload = {"matches": search_sources(request, query, _expand_record_types(record_types))}
        return ToolCallResult(tool="search_sources", success=True, payload=payload)

    if name == "get_sources":
        ids = arguments.get("ids") or []
        if not isinstance(ids, list):
            ids = []
        payload = {"sources": get_sources(request, ids)}
        return ToolCallResult(tool="get_sources", success=True, payload=payload)

    if name == "get_document_facts":
        fields = arguments.get("fields") or []
        if not isinstance(fields, list):
            fields = []
        payload = {
            "facts": get_document_facts(
                request,
                document_type=str(arguments.get("document_type", "") or ""),
                fields=[str(field) for field in fields],
                field_group=str(arguments.get("field_group", "") or ""),
            )
        }
        return ToolCallResult(tool="get_document_facts", success=True, payload=payload)

    if name == "list_adapter_status":
        payload = {
            "adapter_status": [
                {
                    "adapter": status.adapter,
                    "status": status.status,
                    "reason": status.reason,
                }
                for status in request.evidence_bundle.adapter_status
            ]
        }
        return ToolCallResult(tool="list_adapter_status", success=True, payload=payload)

    if name == "summarize_by_type":
        record_types = arguments.get("record_types") or []
        if not isinstance(record_types, list):
            record_types = []
        payload = {
            "summary": summarize_by_type(
                request,
                [str(record_type) for record_type in record_types],
            )
        }
        return ToolCallResult(tool="summarize_by_type", success=True, payload=payload)

    if name == "check_allergy_conflicts":
        return ToolCallResult(
            tool="check_allergy_conflicts",
            success=True,
            payload=check_allergy_conflicts(request),
        )

    return ToolCallResult(tool=_tool_literal(name), success=False, payload={}, error="unknown_tool")


def search_sources(
    request: AgentForgeRequest,
    query: str,
    record_types: list[str],
) -> list[dict]:
    query_terms = _keywords(query)
    hinted_types = _hinted_record_types(query_terms)
    allowed_types = set(_expand_record_types(record_types))
    if hinted_types and not allowed_types:
        allowed_types = hinted_types
    scored: list[tuple[int, EvidenceSource]] = []

    for source in request.evidence_bundle.sources:
        if allowed_types and source.record_type.lower() not in allowed_types:
            continue

        metadata_text = " ".join(str(value) for value in source.metadata.values())
        haystack = f"{source.record_type} {source.field_path} {source.value} {source.note_span or ''} {metadata_text}".lower()
        score = 0
        for term in query_terms:
            if term in haystack:
                score += 2
            if term in source.record_type.lower():
                score += 3
        if source.record_type.lower() in hinted_types:
            score += 4
        if source.record_type.lower() == "document_fact" and "lab" in hinted_types:
            if _is_lab_document_fact(source, metadata_text):
                score += 8
            elif "lab_pdf" in metadata_text.lower():
                score += 1
        if score == 0 and not query_terms:
            score = 1
        if score > 0:
            scored.append((score, source))

    if scored:
        scored.sort(key=lambda item: (item[0], item[1].recorded_at, item[1].id), reverse=True)
        return [_source_payload(source) for _score, source in scored]

    # Keep tool-use non-deterministic while avoiding empty retrieval on broad questions.
    # If lexical matches are sparse, return fallback sources from likely record types.
    fallback_sources = _fallback_sources(request, allowed_types or hinted_types)
    return [_source_payload(source) for source in fallback_sources]


def get_sources(request: AgentForgeRequest, ids: list[str]) -> list[dict]:
    source_by_id = {source.id: source for source in request.evidence_bundle.sources}
    matches = []
    for source_id in ids:
        source = source_by_id.get(source_id)
        if not source:
            continue
        matches.append(_source_payload(source))
    return matches


def get_document_facts(
    request: AgentForgeRequest,
    document_type: str = "",
    fields: list[str] | None = None,
    field_group: str = "",
) -> list[dict]:
    requested_fields = {field.strip().lower() for field in (fields or []) if field}
    group = field_group.strip().lower()
    if group:
        requested_fields |= DOCUMENT_FACT_FIELD_GROUPS.get(group, set())
        if group not in DOCUMENT_FACT_FIELD_GROUPS:
            return []
    normalized_document_type = document_type.strip().lower()
    matches = []
    for source in request.evidence_bundle.sources:
        if source.record_type.lower() != "document_fact":
            continue
        if normalized_document_type and source.metadata.get("document_type", "").lower() != normalized_document_type:
            continue
        citation = _citation_payload(source)
        field_id = str(citation.get("field_or_chunk_id", "")).strip().lower()
        if requested_fields and field_id not in requested_fields and not _document_fact_value_matches_fields(source, requested_fields):
            continue
        matches.append(source)

    matches.sort(key=lambda source: (_document_fact_group_order(source, requested_fields), source.recorded_at, source.id))
    return [_document_fact_payload(source) for source in matches]


def summarize_by_type(request: AgentForgeRequest, record_types: list[str]) -> list[dict]:
    allowed_types = {record_type.strip().lower() for record_type in record_types if record_type}
    grouped: dict[str, list[EvidenceSource]] = {}
    for source in request.evidence_bundle.sources:
        record_type = source.record_type.lower()
        if allowed_types and record_type not in allowed_types:
            continue
        grouped.setdefault(record_type, []).append(source)

    summaries = []
    for record_type in sorted(grouped):
        sources = sorted(grouped[record_type], key=lambda source: (source.recorded_at, source.id), reverse=True)
        summaries.append(
            {
                "record_type": record_type,
                "count": len(sources),
                "representative_sources": [
                    {
                        "id": source.id,
                        "recorded_at": source.recorded_at,
                        "field_path": source.field_path,
                        "value": source.value[:180],
                    }
                    for source in sources
                ],
            }
        )
    return summaries


def check_allergy_conflicts(request: AgentForgeRequest) -> dict:
    allergies = [source for source in request.evidence_bundle.sources if source.record_type.lower() == "allergy"]
    medications = [source for source in request.evidence_bundle.sources if source.record_type.lower() == "medication"]
    conflict_terms = []
    allergy_management_meds = []
    review_pairs = []

    allergy_terms = {
        term
        for allergy in allergies
        for term in _keywords(allergy.value)
        if term not in {"allergy", "allergies", "reaction"}
    }
    allergy_med_terms = {"epinephrine", "loratadine", "cetirizine", "fexofenadine", "diphenhydramine"}

    for medication in medications:
        med_terms = set(_keywords(medication.value))
        overlap = sorted(allergy_terms & med_terms)
        if overlap:
            conflict_terms.extend(overlap)
            review_pairs.append(
                {
                    "medication_source_id": medication.id,
                    "overlap_terms": overlap,
                    "medication_value": medication.value[:180],
                }
            )
        if med_terms & allergy_med_terms:
            allergy_management_meds.append(_source_payload(medication))

    return {
        "allergy_source_ids": [source.id for source in allergies],
        "medication_source_ids": [source.id for source in medications],
        "potential_conflict_terms": sorted(set(conflict_terms)),
        "review_pairs": review_pairs,
        "allergy_management_meds": allergy_management_meds,
    }


def _extract_function_calls(response) -> list[dict]:
    calls: list[dict] = []
    for item in getattr(response, "output", []) or []:
        item_type = getattr(item, "type", None)
        if item_type is None and isinstance(item, dict):
            item_type = item.get("type")
        if item_type != "function_call":
            continue

        name = getattr(item, "name", None) if not isinstance(item, dict) else item.get("name")
        call_id = getattr(item, "call_id", None) if not isinstance(item, dict) else item.get("call_id")
        arguments = getattr(item, "arguments", "{}") if not isinstance(item, dict) else item.get("arguments", "{}")
        if not name or not call_id:
            continue
        calls.append({"name": str(name), "call_id": str(call_id), "arguments": str(arguments)})
    return calls


def _bundle_summary(request: AgentForgeRequest) -> str:
    by_type: dict[str, int] = {}
    for source in request.evidence_bundle.sources:
        by_type[source.record_type] = by_type.get(source.record_type, 0) + 1
    type_counts = ", ".join(f"{record_type}: {count}" for record_type, count in sorted(by_type.items()))
    status_counts = ", ".join(
        f"{status.adapter}={status.status}" for status in request.evidence_bundle.adapter_status
    )
    return f"source_count={len(request.evidence_bundle.sources)}; types=({type_counts}); adapters=({status_counts})"


def _source_payload(source: EvidenceSource) -> dict:
    return {
        "id": source.id,
        "record_type": source.record_type,
        "recorded_at": source.recorded_at,
        "field_path": source.field_path,
        "value": source.value[:280],
        "note_span": (source.note_span or "")[:180],
        "metadata": source.metadata,
    }


def _document_fact_payload(source: EvidenceSource) -> dict:
    payload = _source_payload(source)
    citation = _citation_payload(source)
    payload.update(
        {
            "document_type": source.metadata.get("document_type", ""),
            "label": _document_fact_label(source, citation),
            "field_id": str(citation.get("field_or_chunk_id", "")),
            "citation": citation,
        }
    )
    return payload


def _citation_payload(source: EvidenceSource) -> dict:
    raw = source.metadata.get("citation", "")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _document_fact_label(source: EvidenceSource, citation: dict) -> str:
    field_id = str(citation.get("field_or_chunk_id", "")).strip()
    if field_id:
        return field_id.replace("_", " ").title()
    return source.value.split(";", 1)[0].strip() or "Document Fact"


def _document_fact_value_matches_fields(source: EvidenceSource, fields: set[str]) -> bool:
    haystack = f"{source.field_path} {source.value} {' '.join(str(value) for value in source.metadata.values())}".lower()
    return any(field.replace("_", " ") in haystack or field in haystack for field in fields)


def _document_fact_group_order(source: EvidenceSource, requested_fields: set[str]) -> tuple[int, str]:
    field_id = str(_citation_payload(source).get("field_or_chunk_id", "")).strip().lower()
    ordered = ["phone", "patient_phone", "emergency_contact_phone", "preferred_pharmacy_name", "pharmacy_phone", "pharmacy_address"]
    if field_id in ordered:
        return (ordered.index(field_id), field_id)
    if field_id in requested_fields:
        return (len(ordered), field_id)
    return (len(ordered) + 1, field_id)


def _keywords(text: str) -> list[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "have",
        "has",
        "this",
        "that",
        "does",
        "patient",
        "any",
        "about",
    }
    words = []
    for token in text.split():
        word = token.strip(".,:;!?()[]{}'\"").lower()
        if len(word) < 3 or word in stop:
            continue
        words.append(word)
    return words


def _hinted_record_types(query_terms: list[str]) -> set[str]:
    terms = set(query_terms)
    hinted = set()
    for record_type, hints in SEMANTIC_TYPE_HINTS.items():
        if terms & hints:
            hinted.add(record_type)
    if "lab" in hinted:
        hinted.add("document_fact")
    return hinted


def _expand_record_types(record_types: list[str]) -> list[str]:
    expanded = {record_type.strip().lower() for record_type in record_types if record_type}
    if "lab" in expanded:
        expanded.add("document_fact")
    return sorted(expanded)


def _is_lab_document_fact(source: EvidenceSource, metadata_text: str = "") -> bool:
    haystack = f"{source.field_path} {source.value} {source.note_span or ''} {metadata_text}".lower()
    return any(term in haystack for term in LAB_DOCUMENT_FACT_HINTS)


def _fallback_sources(request: AgentForgeRequest, hinted_types: set[str]) -> list[EvidenceSource]:
    preferred_types = FALLBACK_RECORD_TYPE_ORDER
    if hinted_types:
        preferred_types = sorted(
            FALLBACK_RECORD_TYPE_ORDER,
            key=lambda record_type: (record_type not in hinted_types, FALLBACK_RECORD_TYPE_ORDER.index(record_type)),
        )

    sources = sorted(
        request.evidence_bundle.sources,
        key=lambda source: (source.recorded_at, source.id),
        reverse=True,
    )

    selected: list[EvidenceSource] = []
    seen = set()
    for record_type in preferred_types:
        for source in sources:
            if source.id in seen:
                continue
            if source.record_type.lower() != record_type:
                continue
            selected.append(source)
            seen.add(source.id)
    return selected


def _usage_tokens(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    if isinstance(usage, dict):
        return int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0), int(
            usage.get("output_tokens") or usage.get("completion_tokens") or 0
        )
    return int(getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", 0)) or 0), int(
        getattr(usage, "output_tokens", getattr(usage, "completion_tokens", 0)) or 0
    )


def _tool_literal(name: str) -> ToolName:
    if name in {
        "search_sources",
        "get_sources",
        "get_document_facts",
        "list_adapter_status",
        "summarize_by_type",
        "check_allergy_conflicts",
    }:
        return name
    return "search_sources"
