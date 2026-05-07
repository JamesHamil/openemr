from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ResponseStatus = Literal["verified", "partial", "refused", "failed"]
AdapterStatusValue = Literal["success", "partial", "timeout", "unavailable", "failed"]
SupportStatus = Literal["supported", "unsupported", "conflicting", "blocked"]
DocumentType = Literal["lab_pdf", "intake_form"]
ExtractionStatus = Literal["success", "partial", "failed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scope(StrictModel):
    user_hash: str
    patient_hash: str
    encounter_hash: str
    evidence_bundle_id: str


class PatientContext(StrictModel):
    patient_id: str
    encounter_id: str = ""


class EvidenceSource(StrictModel):
    id: str
    record_type: str
    recorded_at: str
    field_path: str
    value: str
    note_span: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class AdapterStatus(StrictModel):
    adapter: str
    status: AdapterStatusValue
    reason: str = ""
    latency_ms: int | None = None


class RoundingContextBundle(StrictModel):
    id: str
    created_at: str
    patient_context: PatientContext
    sources: list[EvidenceSource] = Field(default_factory=list)
    adapter_status: list[AdapterStatus] = Field(default_factory=list)


class AgentForgeRequest(StrictModel):
    schema_version: Literal["agentforge.request.v1"]
    request_id: str
    conversation_id: str
    expires_at: str
    purpose: str
    scope: Scope
    message: str
    evidence_bundle: RoundingContextBundle


class ResponseSection(StrictModel):
    id: str
    title: str
    claim_ids: list[str] = Field(default_factory=list)


class Claim(StrictModel):
    id: str
    text: str
    claim_type: str
    source_ids: list[str] = Field(default_factory=list)
    support_status: SupportStatus


class ResponseSource(StrictModel):
    id: str
    record_type: str
    display: str
    recorded_at: str
    field_path: str
    extracted_value: str
    metadata: dict[str, str] = Field(default_factory=dict)


class WarningItem(StrictModel):
    code: str
    message: str


class AgentForgeResponse(StrictModel):
    schema_version: Literal["agentforge.response.v1"] = "agentforge.response.v1"
    answer: str
    sections: list[ResponseSection] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    sources: list[ResponseSource] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)
    blocked_claims: list[str] = Field(default_factory=list)
    verification_status: ResponseStatus
    trace_id: str
    debug_trace: dict = Field(default_factory=dict)


class SourceCitation(StrictModel):
    source_type: str
    source_id: str
    page_or_section: str = ""
    field_or_chunk_id: str = ""
    quote_or_value: str = ""
    bounding_box: dict[str, float | int] | None = None


class ExtractedFact(StrictModel):
    fact_type: str
    label: str
    value: str
    unit: str = ""
    reference_range: str = ""
    abnormal_flag: str = ""
    recorded_at: str = ""
    confidence: float = 0.0
    citation: SourceCitation


class WorkerHandoff(StrictModel):
    worker: str
    route_reason: str
    input_summary: str
    output_status: str
    latency_ms: int
    selected_citation_ids: list[str] = Field(default_factory=list)


class DocumentExtractionRequest(StrictModel):
    schema_version: Literal["agentforge.document_extract.v1"]
    request_id: str
    expires_at: str
    document_type: DocumentType
    source_id: str
    filename: str
    mime_type: str
    content_base64: str
    text_hint: str = ""
    scope: Scope


class DocumentExtractionResponse(StrictModel):
    schema_version: Literal["agentforge.document_extract.response.v1"] = "agentforge.document_extract.response.v1"
    document_type: DocumentType
    extraction_status: ExtractionStatus
    extracted_facts: list[ExtractedFact] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)
    worker_handoffs: list[WorkerHandoff] = Field(default_factory=list)
    trace_id: str


ToolName = Literal[
    "search_sources",
    "get_sources",
    "get_document_facts",
    "list_adapter_status",
    "summarize_by_type",
    "check_allergy_conflicts",
]


class ToolCallRequest(StrictModel):
    tool: ToolName
    arguments: dict = Field(default_factory=dict)


class ToolCallResult(StrictModel):
    tool: ToolName
    success: bool
    payload: dict = Field(default_factory=dict)
    error: str = ""


class ClaimDraft(StrictModel):
    text: str
    claim_type: str
    source_ids: list[str] = Field(default_factory=list)


class ToolPhaseResult(StrictModel):
    selected_source_ids: list[str] = Field(default_factory=list)
    drafted_claims: list[ClaimDraft] = Field(default_factory=list)
    focus: str = ""


class TraceRecord(StrictModel):
    trace_id: str
    request_id: str
    conversation_id: str
    mode: str
    verification_status: ResponseStatus
    source_count: int
    collector_statuses: list[AdapterStatus]
    blocked_claim_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    latency_ms: int
    error: str = ""
    tool_call_count: int | None = None
    selected_source_count: int | None = None
    fallback_reason: str | None = None
    planning_latency_ms: int | None = None
    compose_latency_ms: int | None = None
    answer_family: str | None = None
    needed_adapters: list[str] = Field(default_factory=list)
    citation_coverage: float | None = None
    verifier_result: str | None = None
    repair_count: int | None = None
    status_reason: str | None = None
    source_selection_mode: str | None = None
    schema_evidence_expansion: dict = Field(default_factory=dict)
    stale_blocked_claim_count: int | None = None
    valid_blocked_claim_count: int | None = None
    guideline_retrieval_hits: int | None = None
    guideline_rerank_scores: list[float] = Field(default_factory=list)
    guideline_selected_chunk_ids: list[str] = Field(default_factory=list)
    guideline_score_details: list[dict] = Field(default_factory=list)
    supervisor_route: str | None = None
    graph_nodes: list[str] = Field(default_factory=list)
    worker_handoffs: list[WorkerHandoff] = Field(default_factory=list)
