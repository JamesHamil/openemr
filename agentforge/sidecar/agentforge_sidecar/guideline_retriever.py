from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path

from .schemas import AdapterStatus, AgentForgeRequest, EvidenceSource
from .settings import Settings


MAX_GUIDELINES = 3


def augment_with_guidelines(request: AgentForgeRequest, settings: Settings | None = None) -> tuple[AgentForgeRequest, dict]:
    if not request.evidence_bundle.sources:
        return request, {"retrieval_hits": 0, "rerank_scores": []}
    query = _query_text(request)
    chunks = _rank_guidelines(query, settings)[:MAX_GUIDELINES]
    if not chunks:
        return request, {"retrieval_hits": 0, "rerank_scores": []}

    sources = list(request.evidence_bundle.sources)
    for chunk in chunks:
        sources.append(
            EvidenceSource(
                id=chunk["id"],
                record_type="guideline",
                recorded_at=chunk.get("published_at", "2026-01-01T00:00:00Z"),
                field_path=f"guidelines.{chunk.get('section', 'chunk')}",
                value=chunk["text"],
                metadata={
                    "source_kind": "guideline",
                    "title": chunk.get("title", ""),
                    "section": chunk.get("section", ""),
                    "citation_label": chunk.get("citation_label", ""),
                    "score": f"{chunk.get('_score', 0.0):.4f}",
                },
            )
        )

    statuses = list(request.evidence_bundle.adapter_status)
    statuses.append(
        AdapterStatus(
            adapter="guideline_retrieval",
            status="success",
            reason=f"Retrieved {len(chunks)} local guideline snippets.",
        )
    )
    bundle = request.evidence_bundle.model_copy(update={"sources": sources, "adapter_status": statuses})
    return request.model_copy(update={"evidence_bundle": bundle}), {
        "retrieval_hits": len(chunks),
        "rerank_scores": [float(chunk.get("_score", 0.0)) for chunk in chunks],
    }


def _query_text(request: AgentForgeRequest) -> str:
    source_terms = " ".join(
        source.value for source in request.evidence_bundle.sources if source.record_type in {"lab", "document_fact", "problem", "medication"}
    )
    return f"{request.message} {source_terms}"


def _rank_guidelines(query: str, settings: Settings | None = None) -> list[dict]:
    terms = _keywords(query)
    if not terms:
        return []
    embedding_scores = _embedding_scores(query, settings)
    ranked = []
    for chunk in _guideline_chunks():
        text = f"{chunk.get('title', '')} {chunk.get('section', '')} {chunk.get('text', '')}"
        sparse = _sparse_score(terms, text)
        dense = embedding_scores.get(chunk["id"], _hashed_similarity(terms, _keywords(text)))
        score = 0.7 * sparse + 0.3 * dense
        if score > 0:
            item = dict(chunk)
            item["_score"] = score
            ranked.append(item)
    ranked.sort(key=lambda item: (item["_score"], item["id"]), reverse=True)
    return ranked


def _embedding_scores(query: str, settings: Settings | None) -> dict[str, float]:
    if settings is None or settings.mode != "real" or not settings.openai_api_key:
        return {}
    chunks = _guideline_chunks()
    try:
        from openai import OpenAI

        client = OpenAI()
        texts = [query] + [f"{chunk.get('title', '')} {chunk.get('section', '')} {chunk.get('text', '')}" for chunk in chunks]
        response = client.embeddings.create(
            model=os.getenv("AGENTFORGE_EMBEDDING_MODEL", "text-embedding-3-small"),
            input=texts,
        )
        vectors = [item.embedding for item in response.data]
        query_vector = vectors[0]
        return {
            chunk["id"]: _cosine(query_vector, vectors[index + 1])
            for index, chunk in enumerate(chunks)
        }
    except Exception:
        return {}


def _sparse_score(query_terms: list[str], text: str) -> float:
    haystack = text.lower()
    score = 0.0
    for term in query_terms:
        if term in haystack:
            score += 1.0
    return score / max(1, len(set(query_terms)))


def _hashed_similarity(left_terms: list[str], right_terms: list[str]) -> float:
    left = _hashed_vector(left_terms)
    right = _hashed_vector(right_terms)
    dot = sum(left[index] * right[index] for index in range(len(left)))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _hashed_vector(terms: list[str], size: int = 64) -> list[float]:
    vector = [0.0] * size
    for term in terms:
        vector[hash(term) % size] += 1.0
    return vector


def _keywords(text: str) -> list[str]:
    stop = {"the", "and", "for", "with", "from", "that", "this", "patient", "current", "listed"}
    words = []
    for token in text.lower().replace("/", " ").split():
        word = token.strip(".,:;()[]{}'\"")
        if len(word) < 3 or word in stop:
            continue
        words.append(word)
    return words


@lru_cache(maxsize=1)
def _guideline_chunks() -> list[dict]:
    path = Path(__file__).resolve().parents[2] / "guidelines" / "clinical_guidelines.json"
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
