from __future__ import annotations

import time
import uuid

from . import supervisor_graph
from .observability import chat_observation, update_chat_observation
from .openai_provider import openai_response
from .schemas import AgentForgeRequest, AgentForgeResponse, TraceRecord, WarningItem
from .settings import Settings


def handle_chat(request: AgentForgeRequest, settings: Settings) -> tuple[AgentForgeResponse, TraceRecord]:
    started = time.perf_counter()
    trace_id = f"af-{uuid.uuid4()}"
    error = ""
    tool_call_count = None
    selected_source_count = None
    fallback_reason = None
    planning_latency_ms = None
    compose_latency_ms = None
    answer_family = None
    needed_adapters: list[str] = []
    citation_coverage = None
    verifier_result = None
    repair_count = None
    status_reason = None
    source_selection_mode = None
    stale_blocked_claim_count = None
    valid_blocked_claim_count = None
    actual_input_tokens = None
    actual_output_tokens = None
    guideline_retrieval_hits = None
    guideline_rerank_scores: list[float] = []

    with chat_observation(request, settings, trace_id) as chat_span:
        try:
            supervisor_graph.openai_response = openai_response
            graph_result = supervisor_graph.run_chat_graph(request, settings, trace_id)
            response = graph_result.response
            working_request = graph_result.working_request
            guideline_diag = graph_result.guideline_diag
            guideline_retrieval_hits = guideline_diag.get("retrieval_hits")
            guideline_rerank_scores = guideline_diag.get("rerank_scores", [])
            guideline_selected_chunk_ids = guideline_diag.get("selected_chunk_ids", [])
            guideline_score_details = guideline_diag.get("score_details", [])
            fallback_reason = graph_result.fallback_reason or fallback_reason
            supervisor_route = graph_result.supervisor_route
            graph_nodes = graph_result.graph_nodes
            worker_handoffs = graph_result.worker_handoffs
            provider_diagnostics = graph_result.provider_diagnostics
            if provider_diagnostics is not None:
                tool_call_count = provider_diagnostics.tool_call_count
                selected_source_count = provider_diagnostics.selected_source_count
                fallback_reason = provider_diagnostics.fallback_reason or fallback_reason
                planning_latency_ms = provider_diagnostics.planning_latency_ms
                compose_latency_ms = provider_diagnostics.compose_latency_ms
                answer_family = getattr(provider_diagnostics, "answer_family", None)
                needed_adapters = list(getattr(provider_diagnostics, "needed_adapters", ()) or ())
                citation_coverage = getattr(provider_diagnostics, "citation_coverage", None)
                verifier_result = getattr(provider_diagnostics, "verifier_result", None)
                repair_count = getattr(provider_diagnostics, "repair_count", None)
                status_reason = getattr(provider_diagnostics, "status_reason", None)
                source_selection_mode = getattr(provider_diagnostics, "source_selection_mode", None)
                stale_blocked_claim_count = getattr(provider_diagnostics, "stale_blocked_claim_count", None)
                valid_blocked_claim_count = getattr(provider_diagnostics, "valid_blocked_claim_count", None)
                actual_input_tokens = getattr(provider_diagnostics, "input_tokens", None) or None
                actual_output_tokens = getattr(provider_diagnostics, "output_tokens", None) or None
            if response.verification_status == "partial" and not response.claims and response.blocked_claims:
                fallback_reason = fallback_reason or "all_claims_blocked_by_verifier"
        except Exception as exc:
            error = str(exc)
            fallback_reason = fallback_reason or "sidecar_exception"
            response = AgentForgeResponse(
                answer=_focused_uncertainty_answer(request.message),
                sections=[],
                claims=[],
                sources=[],
                warnings=[
                    WarningItem(
                        code="sidecar_exception",
                        message="The sidecar returned a controlled partial fallback.",
                    )
                ],
                blocked_claims=[],
                verification_status="partial",
                trace_id=trace_id,
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        trace = TraceRecord(
            trace_id=trace_id,
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            mode=settings.mode,
            verification_status=response.verification_status,
            source_count=len(locals().get("working_request", request).evidence_bundle.sources),
            collector_statuses=locals().get("working_request", request).evidence_bundle.adapter_status,
            blocked_claim_count=len(response.blocked_claims),
            estimated_input_tokens=actual_input_tokens if actual_input_tokens is not None else _rough_tokens(request.model_dump_json()),
            estimated_output_tokens=actual_output_tokens if actual_output_tokens is not None else _rough_tokens(response.model_dump_json()),
            estimated_cost_usd=0.0,
            latency_ms=latency_ms,
            error=error,
            tool_call_count=tool_call_count,
            selected_source_count=selected_source_count,
            fallback_reason=fallback_reason,
            planning_latency_ms=planning_latency_ms,
            compose_latency_ms=compose_latency_ms,
            answer_family=answer_family,
            needed_adapters=needed_adapters,
            citation_coverage=citation_coverage,
            verifier_result=verifier_result,
            repair_count=repair_count,
            status_reason=status_reason,
            source_selection_mode=source_selection_mode,
            stale_blocked_claim_count=stale_blocked_claim_count,
            valid_blocked_claim_count=valid_blocked_claim_count,
            guideline_retrieval_hits=guideline_retrieval_hits,
            guideline_rerank_scores=guideline_rerank_scores,
            guideline_selected_chunk_ids=locals().get("guideline_selected_chunk_ids", []),
            guideline_score_details=locals().get("guideline_score_details", []),
            supervisor_route=locals().get("supervisor_route"),
            graph_nodes=locals().get("graph_nodes", []),
            worker_handoffs=locals().get("worker_handoffs", []),
        )
        update_chat_observation(chat_span, response, trace, settings)
    return response, trace


def _rough_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _focused_uncertainty_answer(message: str) -> str:
    normalized = " ".join(message.strip().split()).rstrip("?.")
    focus = normalized or "the requested topic"
    return f'I did not find retrieved evidence for "{focus}" in the bounded records; confirm in the chart.'
