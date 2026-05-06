# Week 2 Cost And Latency Report

## Current Local Baseline

Latest deterministic Week 2 eval run:

- cases: 50
- passed: 50
- failed: 0
- p50 latency: 0.00s
- p95 latency: 0.00s
- mode: mock, no paid model calls

The mock run is the CI regression gate. It verifies schema, citation, routing, worker handoffs, safe refusal, PHI-safe traces, and guideline metadata without requiring OpenAI or Langfuse secrets.

## Live Cost Drivers

Live cost is concentrated in four places:

- document extraction for lab PDFs and intake forms;
- optional embedding calls for guideline retrieval;
- answer composition;
- verifier or repair calls when generated claims need correction.

The sidecar records token usage from API usage fields when live model calls return usage metadata. Mock mode continues to use estimates only for deterministic eval logging.

## Latency Bottlenecks

Expected slow stages:

- PDF/image extraction, especially larger or scanned documents;
- network latency to the model provider;
- embedding calls if guideline embeddings are not cached;
- answer composition plus verifier pass.

Bounded controls:

- OpenEMR Documents own files, while AgentForge stores only extracted facts and citations.
- The answer path receives structured document facts, not full PDFs.
- Guideline top-k remains small.
- LangGraph node metadata records supervisor, retriever, answer worker, and verifier latency.

## Scale Notes

At 100 users, a single sidecar instance is acceptable for demo workloads if document extraction is user-triggered and not repeated on every chat. At 1K users, cache guideline embeddings and separate extraction from chat latency. At 10K users, queue extraction jobs, add sidecar replicas, and move trace/export work off the request path. At 100K users, use regional sidecars, managed queues, per-tenant rate limits, and formal PHI/BAA review before live clinical use.

## Reporting Command

```shell
PYTHONPATH=agentforge/sidecar agentforge/sidecar/.venv/bin/python agentforge/evals/run_week2_evals.py --json
```
