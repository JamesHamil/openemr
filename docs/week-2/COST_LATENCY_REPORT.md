# Week 2 Cost And Latency Report

## Executive Summary

AgentForge currently has two measured cost and latency views:

- Deterministic Week 2 regression path: `50/50` cases passing, `p50=2ms`, `p95=3ms`.
- Real development and demo path: `$0.256832` captured model spend across `127` production traces in the reviewed Langfuse window, with interactive demo traces averaging about `$0.0035` per paid chat turn.


## Actual Development And Demo Spend

Source: the Week 1 Langfuse-backed cost analysis in [`docs/week-1/COST_ANALYSIS.md`](../week-1/COST_ANALYSIS.md), covering production traces from `2026-05-01T00:00:00Z` through `2026-05-04T00:00:00Z`.

| Slice | Traces | Paid traces | Total model cost | Avg cost / trace | Avg paid cost | P95 trace cost | Avg latency | P95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All captured traces | 127 | 114 | `$0.256832` | `$0.002022` | `$0.002253` | `$0.005486` | `6.41s` | `15.63s` |
| Interactive demo traces | 19 | 18 | `$0.062474` | `$0.003288` | `$0.003471` | `$0.005764` | `12.22s` | `21.98s` |
| Live eval/dev traces | 108 | 96 | `$0.194358` | `$0.001800` | `$0.002025` | `$0.003655` | `5.38s` | `11.69s` |

The production planning unit is the interactive paid average: `$0.0035` per paid chat turn. A `35%` safety buffer covers longer charts, retries, model variance, and pricing/config drift:

```text
Buffered planning cost per paid chat turn = $0.0035 * 1.35 = $0.0047
```

## P50/P95 Latency Baseline

| Path | Mode | Cases | Paid model calls | P50 latency | P95 latency | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Week 2 eval gate | mock | 50 | 0 | `2ms` | `3ms` | CI-safe deterministic path for schema, citations, routing, safety, and PHI-log checks. |
| Real interactive demo traces | real | 19 | 18 | Not exported in current aggregate | `21.98s` | Langfuse aggregate used for actual spend and live p95; raw trace export is needed for live p50. |
| Real live eval/dev traces | real | 108 | 96 | Not exported in current aggregate | `11.69s` | Lower latency than interactive traces because cases are narrower and less UI-like. |

The p50/p95 requirement is satisfied for the checked-in Week 2 gate. The production readiness gap is live p50 export: the sidecar records per-request latency, but the current written aggregate only includes average and p95 for live Langfuse traces.

## Projected Production Cost

Baseline assumptions:

- `20` clinical workdays per month.
- `12` rounded patients per active clinician per workday.
- `2.5` AgentForge chat turns per patient.
- Paid turns exclude cache hits, mock/off responses, and deterministic source-selection paths.
- Model spend is separate from infrastructure, support, observability, compliance, and backup costs.

| Active users | Gross turns / month | Assumed cache/offload | Paid turns / month | Model cost @ `$0.0035` | Buffered model cost @ `$0.0047` | Architecture posture |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 100 | 60,000 | 20% | 48,000 | `$168/mo` | `$226/mo` | Current OpenEMR, MariaDB, one sidecar, metadata-only traces. |
| 1,000 | 600,000 | 25% | 450,000 | `$1,575/mo` | `$2,126/mo` | Sidecar replicas, OpenEMR-side cache, stricter rate limits. |
| 10,000 | 6,000,000 | 35% | 3,900,000 | `$13,650/mo` | `$18,428/mo` | Queues, autoscaling sidecars, centralized observability, spend budgets. |
| 100,000 | 60,000,000 | 45% | 33,000,000 | `$115,500/mo` | `$155,925/mo` | Enterprise multi-region topology, negotiated pricing, tenant budgets. |

Non-model platform allowance:

| Scale | Suggested non-model allowance | Main drivers |
| ---: | ---: | --- |
| 100 users | `$100-$500/mo` | Railway-style services, one sidecar, low trace volume. |
| 1,000 users | `$500-$2,500/mo` | Sidecar replicas, cache, logs, alerting. |
| 10,000 users | `$5K-$20K/mo` | Autoscaling, queues, centralized observability, database tuning. |
| 100,000 users | `$50K+/mo` | Multi-region operations, compliance program, support, vendor contracts. |

## Bottleneck Analysis

Current bottlenecks:

- Real document extraction is the slowest user-triggered path, especially for images, scanned PDFs, and larger files.
- Real interactive chat latency is dominated by compose, verify, and occasional repair calls.
- Repair calls increase both cost and p95 latency when structured output needs correction.
- Tool-phase/source-selection calls have the highest observed average latency and should stay rare.
- Docker/OpenEMR local development startup is operationally fragile and should not be confused with sidecar model latency.

Controls already in place:

- Mock mode remains deterministic and free for CI, demos, and rollback.
- OpenEMR owns documents; the sidecar stores extracted facts and citations instead of resending full files during chat.
- Guideline top-k is bounded.
- Sidecar traces include timing, token/cost metadata when available, selected source counts, verifier result, repair count, and worker handoffs.
- Re-extraction is user-triggered and saved document facts are reused for RAG.

Next optimizations:

- Export raw Langfuse trace latencies into this report so live p50 appears beside live p95.
- Track extraction latency separately from chat latency.
- Alert on p95 latency, repair rate, tool-phase rate, model errors, and daily spend.
- Cache guideline embeddings and verified response fingerprints within patient/encounter/evidence scope.
- Queue non-urgent document extraction and pre-round summaries at 1K+ active users.

## Reporting Commands

Week 2 deterministic gate:

```shell
PYTHONPATH=agentforge/sidecar agentforge/sidecar/.venv/bin/python agentforge/evals/run_week2_evals.py --json
```

Live-mode eval path, when credentials are available:

```shell
AGENTFORGE_EVAL_MODE=live PYTHONPATH=agentforge/sidecar agentforge/sidecar/.venv/bin/python agentforge/evals/run_week2_evals.py --json
```
