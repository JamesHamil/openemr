# Week 2 PRD Notes

## Assignment Focus

Week 2 expands the Clinical Co-Pilot from structured OpenEMR chart evidence into a multimodal evidence agent. The required capability is intentionally narrow: ingest a lab PDF and an intake form, extract source-cited structured facts, retrieve guideline evidence, route work through an inspectable supervisor plus two workers, and block regressions with eval-driven CI.

## Core Requirements

- Support two document types: `lab_pdf` and `intake_form`.
- Store source documents in OpenEMR and link every derived fact back to source metadata.
- Use strict schemas for extracted lab and intake facts.
- Build basic hybrid RAG over a small guideline corpus.
- Use an inspectable supervisor with `intake-extractor` and `evidence-retriever` workers.
- Preserve machine-readable citations on every factual clinical claim.
- Provide a visual PDF/document source overlay for extracted citations.
- Build a 50-case boolean eval set and PR-blocking gate.
- Track latency, tokens, cost, retrieval hits, extraction confidence, and eval outcomes without logging raw PHI.

## Submission Artifacts

- Root [`W2_ARCHITECTURE.md`](../../W2_ARCHITECTURE.md).
- Week 2 eval dataset, runner, configuration, and results.
- CI evidence showing the eval gate blocks regressions.
- Deployed app with the Week 2 flow available.
- Cost and latency report with p50/p95 and bottleneck analysis.

## Scope Guardrails

- Demo and synthetic data only.
- Two document types before any stretch document type.
- Derived fact persistence is traceable and module-owned for the demo.
- Patient-record facts and guideline evidence remain separate.
- The Week 1 verifier remains the final answer gate.
