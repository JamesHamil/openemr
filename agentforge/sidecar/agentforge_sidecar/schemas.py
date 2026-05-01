from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ResponseStatus = Literal["verified", "partial", "refused", "failed"]
AdapterStatusValue = Literal["success", "partial", "timeout", "unavailable", "failed"]
SupportStatus = Literal["supported", "unsupported", "conflicting", "blocked"]


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


class ToolCallRequest(StrictModel):
    tool: Literal["search_sources", "get_sources", "list_adapter_status"]
    arguments: dict = Field(default_factory=dict)


class ToolCallResult(StrictModel):
    tool: Literal["search_sources", "get_sources", "list_adapter_status"]
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
