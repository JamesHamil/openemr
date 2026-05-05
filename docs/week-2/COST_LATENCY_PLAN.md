# Week 2 Cost And Latency Plan

## What To Measure

Each encounter should record stage-level latency, token usage, estimated cost, and bottleneck metadata:

- OpenEMR document retrieval;
- extraction model call;
- extraction schema validation;
- embedding lookup or creation;
- sparse retrieval;
- dense retrieval;
- local rerank;
- supervisor routing;
- final compose and verification;
- UI response time.

## Expected Bottlenecks

- PDF/image extraction is likely the slowest model step.
- Embeddings can be cached for guideline chunks but not always for new extracted document text.
- Rerank is bounded by keeping the guideline corpus small.
- Final compose and verification remain latency-sensitive because they are user-facing.

## Cost Controls

- Use synthetic/demo documents with bounded page count.
- Cache guideline embeddings at build time or startup.
- Do not send full documents to the answer composer after extraction; send structured facts plus cited snippets.
- Keep top-k retrieval small.
- Use actual API usage fields for token tracking.

## Reporting

The final report should include actual dev spend, p50/p95 latency by stage, projected production cost, and architectural changes needed at larger usage tiers. The Week 1 cost report remains in [`docs/week-1/COST_ANALYSIS.md`](../week-1/COST_ANALYSIS.md).
