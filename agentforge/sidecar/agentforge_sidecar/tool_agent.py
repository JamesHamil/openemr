from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .schemas import AgentForgeRequest, EvidenceSource, ToolCallResult, ToolPhaseResult

MAX_TOOL_CALLS = 6
MAX_TOOL_RESULTS = 8
MAX_SELECTED_SOURCES = 10

FALLBACK_RECORD_TYPE_ORDER = ["problem", "allergy", "medication", "lab", "vital", "note", "demographic"]
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
    "lab": {"lab", "labs", "result", "results", "glucose", "creatinine", "a1c"},
    "vital": {"vital", "vitals", "blood", "pressure", "pulse", "temperature", "weight"},
    "note": {"note", "notes", "assessment", "plan", "history"},
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
                "limit": {"type": "integer"},
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
        "name": "list_adapter_status",
        "description": "Read collector adapter statuses and reasons from OpenEMR evidence collection.",
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
Choose concise, question-specific evidence and avoid unrelated chart inventory."""

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


def run_tool_phase(client, request: AgentForgeRequest, model: str) -> tuple[ToolPhaseResult, ToolPhaseDiagnostics]:
    started = time.perf_counter()
    source_by_id = {source.id: source for source in request.evidence_bundle.sources}
    tool_call_count = 0
    fallback_reason = ""

    summary = _bundle_summary(request)
    response = client.responses.create(
        model=model,
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
            previous_response_id=response.id,
            max_output_tokens=1000,
            input=tool_outputs,
            tools=TOOL_DEFINITIONS,
        )

        if budget_exhausted:
            response = client.responses.create(
                model=model,
                previous_response_id=response.id,
                max_output_tokens=700,
                input=[{"role": "user", "content": TOOL_BUDGET_EXHAUSTED_PROMPT}],
            )
            break

    plan_response = client.responses.parse(
        model=model,
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
        if len(selected_source_ids) >= MAX_SELECTED_SOURCES:
            fallback_reason = fallback_reason or "selected_source_limit_reached"
            break

    if invalid_source_id_count > 0:
        fallback_reason = fallback_reason or "invalid_tool_source_ids_removed"

    result = parsed.model_copy(update={"selected_source_ids": selected_source_ids})
    diagnostics = ToolPhaseDiagnostics(
        tool_call_count=tool_call_count,
        selected_source_count=len(selected_source_ids),
        fallback_reason=fallback_reason,
        planning_latency_ms=int((time.perf_counter() - started) * 1000),
        invalid_source_id_count=invalid_source_id_count,
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
        limit_raw = arguments.get("limit", MAX_TOOL_RESULTS)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = MAX_TOOL_RESULTS
        limit = max(1, min(limit, MAX_TOOL_RESULTS))
        payload = {"matches": search_sources(request, query, record_types, limit)}
        return ToolCallResult(tool="search_sources", success=True, payload=payload)

    if name == "get_sources":
        ids = arguments.get("ids") or []
        if not isinstance(ids, list):
            ids = []
        payload = {"sources": get_sources(request, ids[:MAX_SELECTED_SOURCES])}
        return ToolCallResult(tool="get_sources", success=True, payload=payload)

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

    return ToolCallResult(tool=_tool_literal(name), success=False, payload={}, error="unknown_tool")


def search_sources(
    request: AgentForgeRequest,
    query: str,
    record_types: list[str],
    limit: int,
) -> list[dict]:
    query_terms = _keywords(query)
    hinted_types = _hinted_record_types(query_terms)
    allowed_types = {record_type.strip().lower() for record_type in record_types if record_type}
    if hinted_types and not allowed_types:
        allowed_types = hinted_types
    scored: list[tuple[int, EvidenceSource]] = []

    for source in request.evidence_bundle.sources:
        if allowed_types and source.record_type.lower() not in allowed_types:
            continue

        haystack = f"{source.record_type} {source.field_path} {source.value} {source.note_span or ''}".lower()
        score = 0
        for term in query_terms:
            if term in haystack:
                score += 2
            if term in source.record_type.lower():
                score += 3
        if source.record_type.lower() in hinted_types:
            score += 4
        if score == 0 and not query_terms:
            score = 1
        if score > 0:
            scored.append((score, source))

    if scored:
        scored.sort(key=lambda item: (item[0], item[1].recorded_at, item[1].id), reverse=True)
        return [_source_payload(source) for _score, source in scored[:limit]]

    # Keep tool-use non-deterministic while avoiding empty retrieval on broad questions.
    # If lexical matches are sparse, return a bounded fallback slice from likely record types.
    fallback_sources = _fallback_sources(request, allowed_types or hinted_types, limit)
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
    }


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
        word = token.strip(".,:;()[]{}'\"").lower()
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
    return hinted


def _fallback_sources(request: AgentForgeRequest, hinted_types: set[str], limit: int) -> list[EvidenceSource]:
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
            if len(selected) >= limit:
                return selected
    return selected


def _tool_literal(name: str):
    if name in {"search_sources", "get_sources", "list_adapter_status"}:
        return name
    return "search_sources"
