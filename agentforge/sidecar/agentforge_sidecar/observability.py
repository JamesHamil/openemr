from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from .schemas import AgentForgeRequest, AgentForgeResponse, TraceRecord
    from .settings import Settings


@contextmanager
def chat_observation(
    request: AgentForgeRequest,
    settings: Settings,
    trace_id: str,
) -> Iterator[Any | None]:
    loaded = _load_langfuse(settings)
    if loaded is None:
        yield None
        return

    langfuse, propagate_attributes = loaded
    metadata = _request_metadata(request, settings, trace_id)
    try:
        span_cm = langfuse.start_as_current_observation(
            as_type="span",
            name="agentforge.chat",
            input=_request_input(request, settings.langfuse_capture_payloads),
        )
    except Exception:
        yield None
        return

    try:
        span = span_cm.__enter__()
    except Exception:
        yield None
        return

    try:
        attributes_cm = propagate_attributes(
            user_id=_bounded(request.scope.user_hash),
            session_id=_bounded(request.conversation_id),
            metadata=metadata,
            tags=",".join(("agentforge", settings.mode, *settings.langfuse_tags)),
            trace_name="agentforge.chat",
        )
        attributes_cm.__enter__()
    except Exception:
        _safe_exit(span_cm)
        yield None
        return

    exc_info = (None, None, None)
    try:
        yield span
    except BaseException:
        exc_info = sys.exc_info()
        raise
    finally:
        _safe_exit(attributes_cm, exc_info)
        _safe_exit(span_cm, exc_info)


@contextmanager
def generation_observation(
    name: str,
    settings: Settings,
    model: str,
    input_payload: dict[str, Any],
) -> Iterator[Any | None]:
    loaded = _load_langfuse(settings)
    if loaded is None:
        yield None
        return

    langfuse, _propagate_attributes = loaded
    try:
        gen_cm = langfuse.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=input_payload if settings.langfuse_capture_payloads else _redacted_payload(input_payload),
        )
    except Exception:
        yield None
        return

    try:
        generation = gen_cm.__enter__()
    except Exception:
        yield None
        return

    exc_info = (None, None, None)
    try:
        yield generation
    except BaseException:
        exc_info = sys.exc_info()
        raise
    finally:
        _safe_exit(gen_cm, exc_info)


@contextmanager
def graph_node_observation(
    name: str,
    settings: Settings,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    loaded = _load_langfuse(settings)
    if loaded is None:
        yield None
        return

    langfuse, _propagate_attributes = loaded
    try:
        span_cm = langfuse.start_as_current_observation(
            as_type="span",
            name=name,
            input=_redacted_payload(metadata or {}),
            metadata=_redacted_payload(metadata or {}),
        )
    except Exception:
        yield None
        return

    try:
        span = span_cm.__enter__()
    except Exception:
        yield None
        return

    exc_info = (None, None, None)
    try:
        yield span
    except BaseException:
        exc_info = sys.exc_info()
        raise
    finally:
        _safe_exit(span_cm, exc_info)


def update_chat_observation(
    observation: Any | None,
    response: AgentForgeResponse,
    trace: TraceRecord,
    settings: Settings,
) -> None:
    if observation is None:
        return

    output = {
        "verification_status": response.verification_status,
        "blocked_claim_count": len(response.blocked_claims),
        "warning_codes": [warning.code for warning in response.warnings],
        "claim_count": len(response.claims),
        "source_count": len(response.sources),
    }
    if settings.langfuse_capture_payloads:
        output["answer"] = response.answer
        output["claims"] = [claim.model_dump() for claim in response.claims]
        output["sources"] = [source.model_dump() for source in response.sources]

    _safe_update(
        observation,
        output=output,
        metadata={
            "verification_status": trace.verification_status,
            "latency_ms": trace.latency_ms,
            "estimated_input_tokens": trace.estimated_input_tokens,
            "estimated_output_tokens": trace.estimated_output_tokens,
            "estimated_cost_usd": trace.estimated_cost_usd,
            "tool_call_count": trace.tool_call_count,
            "selected_source_count": trace.selected_source_count,
            "fallback_reason": trace.fallback_reason or "",
            "planning_latency_ms": trace.planning_latency_ms,
            "compose_latency_ms": trace.compose_latency_ms,
            "verify_latency_ms": trace.verify_latency_ms,
            "repair_latency_ms": trace.repair_latency_ms,
            "model_call_count": trace.model_call_count,
            "answer_family": trace.answer_family or "",
            "needed_adapters": ",".join(trace.needed_adapters),
            "citation_coverage": trace.citation_coverage,
            "verifier_result": trace.verifier_result or "",
            "repair_count": trace.repair_count,
            "status_reason": trace.status_reason or "",
            "source_selection_mode": trace.source_selection_mode or "",
            "latency_strategy": trace.latency_strategy or "",
            "verify_mode": trace.verify_mode or "",
            "cache_hit": trace.cache_hit,
            "stale_blocked_claim_count": trace.stale_blocked_claim_count,
            "valid_blocked_claim_count": trace.valid_blocked_claim_count,
            "supervisor_route": trace.supervisor_route or "",
            "graph_nodes": ",".join(trace.graph_nodes),
            "worker_handoffs": ",".join(handoff.worker for handoff in trace.worker_handoffs),
            "guideline_selected_chunk_ids": ",".join(trace.guideline_selected_chunk_ids),
            "guideline_retrieval_hits": trace.guideline_retrieval_hits,
            "error": trace.error,
        },
    )


def update_generation_observation(
    observation: Any | None,
    settings: Settings,
    output_payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    if observation is None:
        return
    _safe_update(
        observation,
        output=output_payload if settings.langfuse_capture_payloads else _redacted_payload(output_payload),
        metadata=metadata or {},
    )


def update_graph_node_observation(
    observation: Any | None,
    settings: Settings,
    output_payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    if observation is None:
        return
    _safe_update(
        observation,
        output=_redacted_payload(output_payload),
        metadata=_redacted_payload(metadata or {}),
    )


def flush_langfuse(settings: Settings) -> None:
    if not settings.langfuse_enabled or not settings.langfuse_flush_at_end:
        return
    loaded = _load_langfuse(settings)
    if loaded is None:
        return
    langfuse, _propagate_attributes = loaded
    try:
        langfuse.flush()
    except Exception:
        return


def _load_langfuse(settings: Settings):
    if not settings.langfuse_enabled:
        return None
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse import get_client, propagate_attributes
    except Exception:
        return None
    try:
        return get_client(), propagate_attributes
    except Exception:
        return None


def _request_metadata(request: AgentForgeRequest, settings: Settings, trace_id: str) -> dict[str, Any]:
    statuses = request.evidence_bundle.adapter_status
    return {
        "agentforgeTraceId": trace_id,
        "requestId": request.request_id,
        "conversationId": request.conversation_id,
        "purpose": request.purpose,
        "mode": settings.mode,
        "model": settings.model,
        "environment": settings.langfuse_environment,
        "evidenceBundleId": request.scope.evidence_bundle_id,
        "patientHash": request.scope.patient_hash,
        "encounterHash": request.scope.encounter_hash,
        "sourceCount": str(len(request.evidence_bundle.sources)),
        "adapterCount": str(len(statuses)),
        "adapterStatuses": ",".join(f"{status.adapter}:{status.status}" for status in statuses),
    }


def _request_input(request: AgentForgeRequest, capture_payloads: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": request.request_id,
        "conversation_id": request.conversation_id,
        "purpose": request.purpose,
        "message_length": len(request.message),
        "source_count": len(request.evidence_bundle.sources),
        "source_types": sorted({source.record_type for source in request.evidence_bundle.sources}),
    }
    if not capture_payloads:
        return payload

    payload["message"] = request.message
    payload["sources"] = [
        {
            "id": source.id,
            "record_type": source.record_type,
            "recorded_at": source.recorded_at,
            "field_path": source.field_path,
            "value": source.value[:280],
            "note_span": (source.note_span or "")[:180],
            "metadata": source.metadata,
        }
        for source in request.evidence_bundle.sources
    ]
    payload["adapter_status"] = [status.model_dump() for status in request.evidence_bundle.adapter_status]
    return payload


def _redacted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"message", "prompt", "input", "output", "answer", "sources", "selected_sources", "drafted_claims"}:
            redacted[f"{key}_redacted"] = True
            continue
        if isinstance(value, str):
            redacted[key] = _bounded(value)
            continue
        redacted[key] = value
    return redacted


def _safe_update(observation: Any, **kwargs: Any) -> None:
    try:
        observation.update(**kwargs)
    except Exception:
        return


def _safe_exit(context_manager: Any, exc_info: tuple[Any, Any, Any] = (None, None, None)) -> None:
    try:
        context_manager.__exit__(*exc_info)
    except Exception:
        return


def _bounded(value: str, limit: int = 200) -> str:
    return value[:limit]
