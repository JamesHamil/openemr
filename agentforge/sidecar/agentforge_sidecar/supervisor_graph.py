from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, TypedDict

try:
    from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

    warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)
except Exception:
    pass

from langgraph.graph import END, START, StateGraph

from .clinical_planner import plan_evidence
from .guideline_retriever import augment_with_guidelines
from .mock_provider import mock_response
from .observability import graph_node_observation, update_graph_node_observation
from .openai_provider import ProviderDiagnostics, openai_response
from .schemas import (
    AgentForgeRequest,
    AgentForgeResponse,
    DocumentExtractionRequest,
    DocumentExtractionResponse,
    WarningItem,
    WorkerHandoff,
)
from .settings import Settings
from .verifier import is_treatment_directive, verify_response


@dataclass
class ChatGraphResult:
    response: AgentForgeResponse
    working_request: AgentForgeRequest
    provider_diagnostics: ProviderDiagnostics | None = None
    guideline_diag: dict = field(default_factory=dict)
    fallback_reason: str | None = None
    supervisor_route: str = ""
    graph_nodes: list[str] = field(default_factory=list)
    worker_handoffs: list[WorkerHandoff] = field(default_factory=list)


@dataclass
class DocumentGraphResult:
    response: DocumentExtractionResponse
    diagnostics: dict


class ChatGraphState(TypedDict, total=False):
    request: AgentForgeRequest
    settings: Settings
    trace_id: str
    working_request: AgentForgeRequest
    response: AgentForgeResponse
    provider_diagnostics: ProviderDiagnostics
    guideline_diag: dict
    fallback_reason: str
    supervisor_route: str
    graph_nodes: list[str]
    worker_handoffs: list[WorkerHandoff]


class DocumentGraphState(TypedDict, total=False):
    request: DocumentExtractionRequest
    settings: Settings
    trace_id: str
    started: float
    response: DocumentExtractionResponse
    diagnostics: dict
    graph_nodes: list[str]


RealExtractCallback = Callable[
    [DocumentExtractionRequest, Settings, str, float],
    tuple[DocumentExtractionResponse, dict],
]
HeuristicExtractCallback = Callable[
    [DocumentExtractionRequest, str, float],
    tuple[DocumentExtractionResponse, dict],
]
FailedResponseCallback = Callable[
    [DocumentExtractionRequest, str, str, str, float],
    tuple[DocumentExtractionResponse, dict],
]


def run_chat_graph(request: AgentForgeRequest, settings: Settings, trace_id: str) -> ChatGraphResult:
    state = _chat_graph().invoke(
        {
            "request": request,
            "settings": settings,
            "trace_id": trace_id,
            "working_request": request,
            "guideline_diag": {"retrieval_hits": 0, "rerank_scores": [], "selected_chunk_ids": [], "score_details": []},
            "graph_nodes": [],
            "worker_handoffs": [],
        }
    )
    return ChatGraphResult(
        response=state["response"],
        working_request=state.get("working_request", request),
        provider_diagnostics=state.get("provider_diagnostics"),
        guideline_diag=state.get("guideline_diag", {}),
        fallback_reason=state.get("fallback_reason"),
        supervisor_route=state.get("supervisor_route", ""),
        graph_nodes=state.get("graph_nodes", []),
        worker_handoffs=state.get("worker_handoffs", []),
    )


def run_document_extraction_graph(
    request: DocumentExtractionRequest,
    settings: Settings,
    trace_id: str,
    started: float,
    real_extract: RealExtractCallback,
    heuristic_extract: HeuristicExtractCallback,
    failed_response: FailedResponseCallback,
) -> DocumentGraphResult:
    graph = _document_graph(real_extract, heuristic_extract, failed_response)
    state = graph.invoke(
        {
            "request": request,
            "settings": settings,
            "trace_id": trace_id,
            "started": started,
            "graph_nodes": [],
        }
    )
    diagnostics = dict(state.get("diagnostics", {}))
    diagnostics["graph_nodes"] = state.get("graph_nodes", [])
    return DocumentGraphResult(response=state["response"], diagnostics=diagnostics)


@lru_cache(maxsize=1)
def _chat_graph():
    graph = StateGraph(ChatGraphState)
    graph.add_node("supervisor", _chat_supervisor)
    graph.add_node("evidence_retriever", _evidence_retriever)
    graph.add_node("answer_worker", _answer_worker)
    graph.add_node("critic_verifier", _critic_verifier)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", _after_supervisor, {"retrieve": "evidence_retriever", "answer": "answer_worker", "end": END})
    graph.add_edge("evidence_retriever", "answer_worker")
    graph.add_edge("answer_worker", "critic_verifier")
    graph.add_edge("critic_verifier", END)
    return graph.compile()


def _document_graph(
    real_extract: RealExtractCallback,
    heuristic_extract: HeuristicExtractCallback,
    failed_response: FailedResponseCallback,
):
    graph = StateGraph(DocumentGraphState)
    graph.add_node("supervisor", _document_supervisor(failed_response))
    graph.add_node("intake_extractor", _intake_extractor(real_extract, heuristic_extract))
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", _after_document_supervisor, {"extract": "intake_extractor", "end": END})
    graph.add_edge("intake_extractor", END)
    return graph.compile()


def _chat_supervisor(state: ChatGraphState) -> dict:
    request = state["request"]
    settings = state["settings"]
    trace_id = state["trace_id"]
    started = time.perf_counter()
    route = _initial_chat_route(request)
    response = None
    fallback_reason = ""

    with graph_node_observation("agentforge.supervisor", settings, {"route": route, "source_count": len(request.evidence_bundle.sources)}) as span:
        if any(
            status.adapter == "authorization" and status.status == "failed"
            for status in request.evidence_bundle.adapter_status
        ):
            route = "refuse_unauthorized"
            fallback_reason = "unauthorized_patient_refused"
            response = AgentForgeResponse(
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
        elif is_treatment_directive(request.message):
            route = "refuse_treatment_directive"
            fallback_reason = "treatment_directive_refused"
            response = AgentForgeResponse(
                answer=(
                    "I cannot provide treatment directives. I can summarize retrieved chart evidence "
                    "and record-backed issues for physician review."
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
        elif settings.mode == "off":
            route = "agentforge_off"
            fallback_reason = "agentforge_off"
            response = AgentForgeResponse(
                answer="Clinical Co-Pilot is currently disabled.",
                sections=[],
                claims=[],
                sources=[],
                warnings=[
                    WarningItem(
                        code="agentforge_off",
                        message="The sidecar is configured in off mode.",
                    )
                ],
                blocked_claims=[],
                verification_status="failed",
                trace_id=trace_id,
            )

        handoff = _handoff(
            worker="supervisor",
            route_reason=f"Route decision: {route}.",
            input_summary=f"message_length={len(request.message)} source_count={len(request.evidence_bundle.sources)}",
            output_status=route,
            started=started,
            selected=[],
        )
        update_graph_node_observation(
            span,
            settings,
            {"route": route, "output_status": route},
            {"latency_ms": handoff.latency_ms, "warning_codes": [warning.code for warning in response.warnings] if response else []},
        )

    updates = {
        "supervisor_route": route,
        "graph_nodes": [*state.get("graph_nodes", []), "supervisor"],
        "worker_handoffs": [*state.get("worker_handoffs", []), handoff],
    }
    if response is not None:
        updates["response"] = _attach_debug_trace(response, updates["graph_nodes"], route, updates["worker_handoffs"], state.get("guideline_diag", {}))
    if fallback_reason:
        updates["fallback_reason"] = fallback_reason
    return updates


def _after_supervisor(state: ChatGraphState) -> str:
    if "response" in state:
        return "end"
    if state.get("supervisor_route") in {"answer_document_facts", "answer_direct_evidence"}:
        return "answer"
    return "retrieve"


def _initial_chat_route(request: AgentForgeRequest) -> str:
    try:
        plan = plan_evidence(request)
    except Exception:
        return "retrieve_then_answer"
    if plan.answer_family == "document_facts":
        return "answer_document_facts"
    if plan.answer_family in {"labs", "visit_history"}:
        return "answer_direct_evidence"
    if plan.answer_family == "med_reconciliation" and _plan_selected_medication_evidence(request, plan.selected_source_ids):
        return "answer_direct_evidence"
    return "retrieve_then_answer"


def _plan_selected_medication_document_facts(
    request: AgentForgeRequest,
    selected_source_ids: tuple[str, ...],
) -> bool:
    selected = set(selected_source_ids)
    for source in request.evidence_bundle.sources:
        if source.id not in selected or source.record_type != "document_fact":
            continue
        if source.metadata.get("document_type") == "medication_list":
            return True
    return False


def _plan_selected_medication_evidence(
    request: AgentForgeRequest,
    selected_source_ids: tuple[str, ...],
) -> bool:
    selected = set(selected_source_ids)
    for source in request.evidence_bundle.sources:
        if source.id not in selected:
            continue
        if source.record_type == "medication":
            return True
        if source.record_type == "document_fact" and source.metadata.get("document_type") == "medication_list":
            return True
    return False


def _evidence_retriever(state: ChatGraphState) -> dict:
    request = state["request"]
    settings = state["settings"]
    started = time.perf_counter()
    with graph_node_observation(
        "agentforge.evidence_retriever",
        settings,
        {"route": state.get("supervisor_route", ""), "source_count": len(request.evidence_bundle.sources)},
    ) as span:
        working_request, guideline_diag = augment_with_guidelines(request, settings)
        selected = list(guideline_diag.get("selected_chunk_ids", []))
        handoff = _handoff(
            worker="evidence-retriever",
            route_reason="Retrieve local clinical guideline snippets and preserve patient-record evidence separately.",
            input_summary=f"source_count={len(request.evidence_bundle.sources)}",
            output_status=f"hits={guideline_diag.get('retrieval_hits', 0)}",
            started=started,
            selected=selected,
        )
        update_graph_node_observation(
            span,
            settings,
            {"retrieval_hits": guideline_diag.get("retrieval_hits", 0), "selected_chunk_ids": selected},
            {"latency_ms": handoff.latency_ms, "score_details": guideline_diag.get("score_details", [])},
        )
    return {
        "working_request": working_request,
        "guideline_diag": guideline_diag,
        "graph_nodes": [*state.get("graph_nodes", []), "evidence_retriever"],
        "worker_handoffs": [*state.get("worker_handoffs", []), handoff],
    }


def _answer_worker(state: ChatGraphState) -> dict:
    request = state.get("working_request", state["request"])
    settings = state["settings"]
    trace_id = state["trace_id"]
    started = time.perf_counter()
    with graph_node_observation(
        "agentforge.answer_worker",
        settings,
        {"mode": settings.mode, "source_count": len(request.evidence_bundle.sources)},
    ) as span:
        if settings.mode == "real":
            response, diagnostics = openai_response(request, trace_id, settings)
        else:
            response = mock_response(request, trace_id)
            diagnostics = None
        handoff = _handoff(
            worker="answer-worker",
            route_reason="Compose bounded answer from selected patient/document/guideline evidence.",
            input_summary=f"source_count={len(request.evidence_bundle.sources)} mode={settings.mode}",
            output_status=response.verification_status,
            started=started,
            selected=[source.id for source in response.sources],
        )
        update_graph_node_observation(
            span,
            settings,
            {"verification_status": response.verification_status, "source_count": len(response.sources)},
            {"latency_ms": handoff.latency_ms, "claim_count": len(response.claims)},
        )
    return {
        "response": response,
        "provider_diagnostics": diagnostics,
        "graph_nodes": [*state.get("graph_nodes", []), "answer_worker"],
        "worker_handoffs": [*state.get("worker_handoffs", []), handoff],
    }


def _critic_verifier(state: ChatGraphState) -> dict:
    request = state.get("working_request", state["request"])
    response = state["response"]
    settings = state["settings"]
    started = time.perf_counter()
    with graph_node_observation(
        "agentforge.critic_verifier",
        settings,
        {"incoming_status": response.verification_status, "claim_count": len(response.claims)},
    ) as span:
        verified = response
        if response.verification_status not in {"refused", "failed"}:
            verified = verify_response(request, response)
        handoff = _handoff(
            worker="critic-verifier",
            route_reason="Verify generated claims against selected sources before returning.",
            input_summary=f"claim_count={len(response.claims)}",
            output_status=verified.verification_status,
            started=started,
            selected=[source.id for source in verified.sources],
        )
        graph_nodes = [*state.get("graph_nodes", []), "critic_verifier"]
        handoffs = [*state.get("worker_handoffs", []), handoff]
        verified = _attach_debug_trace(
            verified,
            graph_nodes,
            state.get("supervisor_route", ""),
            handoffs,
            state.get("guideline_diag", {}),
        )
        update_graph_node_observation(
            span,
            settings,
            {"verification_status": verified.verification_status, "blocked_claim_count": len(verified.blocked_claims)},
            {"latency_ms": handoff.latency_ms, "warning_codes": [warning.code for warning in verified.warnings]},
        )
    return {"response": verified, "graph_nodes": graph_nodes, "worker_handoffs": handoffs}


def _document_supervisor(failed_response: FailedResponseCallback):
    def node(state: DocumentGraphState) -> dict:
        request = state["request"]
        settings = state["settings"]
        trace_id = state["trace_id"]
        started = state["started"]
        route = "extract_document"
        with graph_node_observation(
            "agentforge.supervisor",
            settings,
            {"document_type": request.document_type, "mime_type": request.mime_type},
        ) as span:
            if settings.mode == "off":
                route = "agentforge_off"
                response, diagnostics = failed_response(
                    request,
                    trace_id,
                    "agentforge_off",
                    "The sidecar is configured in off mode.",
                    started,
                )
                update_graph_node_observation(span, settings, {"route": route}, {"latency_ms": diagnostics.get("latency_ms")})
                return {
                    "response": response,
                    "diagnostics": {**diagnostics, "supervisor_route": route},
                    "graph_nodes": [*state.get("graph_nodes", []), "supervisor"],
                }
            update_graph_node_observation(span, settings, {"route": route}, {"document_type": request.document_type})
        return {
            "diagnostics": {"supervisor_route": route},
            "graph_nodes": [*state.get("graph_nodes", []), "supervisor"],
        }

    return node


def _after_document_supervisor(state: DocumentGraphState) -> str:
    return "end" if "response" in state else "extract"


def _intake_extractor(real_extract: RealExtractCallback, heuristic_extract: HeuristicExtractCallback):
    def node(state: DocumentGraphState) -> dict:
        request = state["request"]
        settings = state["settings"]
        trace_id = state["trace_id"]
        started = state["started"]
        with graph_node_observation(
            "agentforge.intake_extractor",
            settings,
            {"document_type": request.document_type, "mime_type": request.mime_type},
        ) as span:
            if settings.mode == "real":
                try:
                    response, diagnostics = real_extract(request, settings, trace_id, started)
                except Exception as exc:
                    response, diagnostics = heuristic_extract(request, trace_id, started)
                    response.warnings.append(
                        WarningItem(
                            code="real_extraction_fallback",
                            message=f"Real extraction failed; heuristic extraction was used for demo continuity: {exc}",
                        )
                    )
                    response = response.model_copy(update={"extraction_status": "partial"})
                    diagnostics["fallback_reason"] = "real_extraction_fallback"
            else:
                response, diagnostics = heuristic_extract(request, trace_id, started)

            diagnostics = {**diagnostics, "supervisor_route": state.get("diagnostics", {}).get("supervisor_route", "extract_document")}
            update_graph_node_observation(
                span,
                settings,
                {"extraction_status": response.extraction_status, "fact_count": len(response.extracted_facts)},
                {
                    "latency_ms": diagnostics.get("latency_ms"),
                    "warning_codes": [warning.code for warning in response.warnings],
                    "selected_citation_ids": response.worker_handoffs[-1].selected_citation_ids if response.worker_handoffs else [],
                },
            )
        return {
            "response": response,
            "diagnostics": diagnostics,
            "graph_nodes": [*state.get("graph_nodes", []), "intake_extractor"],
        }

    return node


def _handoff(
    worker: str,
    route_reason: str,
    input_summary: str,
    output_status: str,
    started: float,
    selected: list[str],
) -> WorkerHandoff:
    return WorkerHandoff(
        worker=worker,
        route_reason=route_reason,
        input_summary=input_summary,
        output_status=output_status,
        latency_ms=int((time.perf_counter() - started) * 1000),
        selected_citation_ids=selected,
    )


def _attach_debug_trace(
    response: AgentForgeResponse,
    graph_nodes: list[str],
    supervisor_route: str,
    handoffs: list[WorkerHandoff],
    guideline_diag: dict,
) -> AgentForgeResponse:
    debug_trace = dict(response.debug_trace)
    debug_trace.update(
        {
            "supervisor_route": supervisor_route,
            "graph_nodes": graph_nodes,
            "worker_handoffs": [handoff.model_dump() for handoff in handoffs],
            "guideline_retrieval": {
                "hits": guideline_diag.get("retrieval_hits", 0),
                "selected_chunk_ids": guideline_diag.get("selected_chunk_ids", []),
                "score_details": guideline_diag.get("score_details", []),
            },
        }
    )
    return response.model_copy(update={"debug_trace": debug_trace})
