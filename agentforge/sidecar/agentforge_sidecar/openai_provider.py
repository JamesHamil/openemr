from __future__ import annotations

import json

from .mock_provider import mock_response
from .schemas import AgentForgeRequest, AgentForgeResponse


SYSTEM_PROMPT = """You are AgentForge Clinical Co-Pilot for a hospitalist preparing for rounds.
Use only the provided evidence bundle. Never provide treatment directives, orders, diagnoses,
or medication changes. Every factual clinical claim must cite source_ids from the evidence.

Choose the output shape that best fits the user request:
- Chart brief: one-liner, active chart issues, meds/allergies, recent objective data,
  missing data, and questions/issues for physician review.
- Follow-up question: direct answer first, then supporting evidence and missing-data notes.
- Treatment/action request: refuse the directive and offer to summarize record-backed issues.

Keep the answer concise and scannable: <=180 words, <=8 claims, <=10 displayed sources.
Use answer for a short one-liner/direct answer and put detailed facts in claims/sections.
Return only sources that are cited by the kept claims. Keep each extracted_value short.
Say evidence was not found in retrieved records rather than absent from reality."""


def openai_response(request: AgentForgeRequest, trace_id: str, model: str) -> AgentForgeResponse:
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - depends on runtime dependency
        failed = mock_response(request, trace_id)
        return failed.model_copy(
            update={
                "answer": f"OpenAI real mode is not available in this runtime: {exc}",
                "claims": [],
                "sources": [],
                "warnings": [],
                "blocked_claims": [],
                "verification_status": "failed",
            }
        )

    client = OpenAI()
    payload = request.model_dump()
    response = client.responses.parse(
        model=model,
        max_output_tokens=2600,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Return a JSON response matching the AgentForgeResponse schema for this request:\n"
                + json.dumps(payload, separators=(",", ":")),
            },
        ],
        text_format=AgentForgeResponse,
    )
    parsed = response.output_parsed
    if not parsed:
        raise RuntimeError("OpenAI response did not include parsed AgentForgeResponse output")
    return _limit_response(parsed.model_copy(update={"trace_id": trace_id}))


def _limit_response(response: AgentForgeResponse) -> AgentForgeResponse:
    kept_claims = []
    kept_source_ids: list[str] = []
    kept_claim_ids = set()

    for claim in response.claims:
        candidate_source_ids = [source_id for source_id in claim.source_ids if source_id not in kept_source_ids]
        if len(kept_claims) >= 8 or len(kept_source_ids) + len(candidate_source_ids) > 10:
            continue
        kept_claims.append(claim)
        kept_claim_ids.add(claim.id)
        kept_source_ids.extend(candidate_source_ids)

    response_sources = []
    for source in response.sources:
        if source.id in kept_source_ids and len(response_sources) < 10:
            response_sources.append(source)

    sections = []
    for section in response.sections:
        claim_ids = [claim_id for claim_id in section.claim_ids if claim_id in kept_claim_ids]
        if claim_ids:
            sections.append(section.model_copy(update={"claim_ids": claim_ids}))

    return response.model_copy(
        update={
            "claims": kept_claims,
            "sections": sections,
            "sources": response_sources,
        }
    )
