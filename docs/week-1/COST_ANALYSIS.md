# AgentForge AI Cost Analysis

## Summary

AgentForge cost is driven by clinical workflow shape, evidence-bundle size, retry rate, cache behavior, model choice, verification strategy, trace retention, and deployment topology. It is not simply `cost per token * users`.

The current real-mode path uses `gpt-5-nano` through Langfuse-observed OpenAI generations. A typical paid chat turn contains:

- `agentforge.compose_response`: writes the clinician-facing answer.
- `agentforge.verify_response`: checks source support.
- `agentforge.repair_response`: used when structured output needs repair.
- `agentforge.tool_phase`: used on a subset of real-mode traces when source selection needs an LLM step.

Mock and off modes still cost no model tokens and remain useful for deterministic demos, evals, and rollback.

## Inputs Used

This analysis uses:

- Langfuse production traces from `2026-05-01T00:00:00Z` through `2026-05-04T00:00:00Z`.
- The provided Langfuse screenshots showing representative `agentforge.chat` traces:
  - `6.64s`, `$0.003266` total, with compose `$0.001505` and verify `$0.001762`.
  - `5.41s`, `$0.002368` total, with compose `$0.001154` and verify `$0.001214`.
- Current architecture: OpenEMR module -> signed evidence bundle -> private sidecar -> structured LLM response -> verifier -> OpenEMR UI.

All dollar values below are model/provider costs observed by Langfuse unless an infrastructure allowance is explicitly called out.

## Actual Development And Demo Spend

Langfuse captured `127` production `agentforge.chat` traces in the reviewed window.

| Slice | Traces | Paid traces | Total model cost | Avg cost / trace | Avg paid cost | P95 trace cost | Avg latency | P95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All captured traces | 127 | 114 | `$0.256832` | `$0.002022` | `$0.002253` | `$0.005486` | `6.41s` | `15.63s` |
| Interactive demo traces | 19 | 18 | `$0.062474` | `$0.003288` | `$0.003471` | `$0.005764` | `12.22s` | `21.98s` |
| Live eval/dev traces | 108 | 96 | `$0.194358` | `$0.001800` | `$0.002025` | `$0.003655` | `5.38s` | `11.69s` |

The best planning number for production is the interactive paid average, `$0.0035` per paid chat turn, because it reflects real OpenEMR UI questions more closely than synthetic eval traces. For budgeting, this document also uses a `35%` safety buffer for longer charts, model variance, retries, and pricing/config drift:

```text
Buffered planning cost per paid chat turn = $0.0035 * 1.35 = $0.0047
```

## Observed Model Call Breakdown

Langfuse generation metrics show the current real-mode request shape.

| Observation | Count | Input tokens | Output tokens | Total tokens | Total cost | Avg cost / call | Avg latency | P95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `agentforge.compose_response` | 109 | 35,951 | 10,912 | 46,863 | `$0.076067` | `$0.000698` | `3.42s` | `5.92s` |
| `agentforge.verify_response` | 109 | 100,099 | 9,798 | 109,897 | `$0.119165` | `$0.001093` | `1.49s` | `2.78s` |
| `agentforge.repair_response` | 44 | 50,151 | 3,870 | 54,021 | `$0.055028` | `$0.001251` | `3.43s` | `5.71s` |
| `agentforge.tool_phase` | 15 | 2,066 | 1,116 | 3,182 | `$0.006572` | `$0.000438` | `8.21s` | `15.27s` |

Amortized across the `109` compose/verify request paths, the observed generation cost is:

```text
($0.076067 + $0.119165 + $0.055028 + $0.006572) / 109 = $0.00236 per request path
```

The higher interactive average (`$0.0035`) is used for production planning because it includes fuller end-to-end trace behavior and better matches the provided screenshots.

## Production Workload Assumptions

Baseline monthly model:

- `20` clinical workdays per month.
- `12` rounded patients per active clinician per workday.
- `2.5` AgentForge chat turns per patient: one brief plus follow-ups.
- OpenEMR-side response/evidence caching improves with scale.
- Paid request count excludes cache hits and mock/off responses.
- Infrastructure is budgeted separately from model cost.

Sensitivity:

- Low usage: `8` patients/day, `1.5` turns/patient, higher cache reuse.
- Baseline usage: `12` patients/day, `2.5` turns/patient.
- High usage: `18` patients/day, `4` turns/patient, lower cache reuse and more follow-ups.

## Production Cost Projection

Baseline formula:

```text
gross turns/month = users * workdays * patients/day * turns/patient
paid turns/month = gross turns/month * (1 - cache/offload rate)
model cost/month = paid turns/month * observed interactive paid cost
buffered model cost/month = paid turns/month * buffered planning cost
```

| Active users | Gross turns / month | Assumed cache/offload | Paid turns / month | Model cost @ `$0.0035` | Buffered model cost @ `$0.0047` | Architecture posture |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 100 | 60,000 | 20% | 48,000 | `$168/mo` | `$226/mo` | Single OpenEMR app, MariaDB, one sidecar, metadata traces |
| 1,000 | 600,000 | 25% | 450,000 | `$1,575/mo` | `$2,126/mo` | Sidecar replicas, OpenEMR-side cache, stricter rate limits |
| 10,000 | 6,000,000 | 35% | 3,900,000 | `$13,650/mo` | `$18,428/mo` | Queues, autoscaling sidecars, centralized observability, budgets |
| 100,000 | 60,000,000 | 45% | 33,000,000 | `$115,500/mo` | `$155,925/mo` | Enterprise multi-region platform, negotiated pricing, tenant budgets |

## Low / Baseline / High Usage Ranges

The same user count can produce very different spend depending on adoption and cache behavior.

| Active users | Low usage model cost | Baseline model cost | High usage model cost |
| ---: | ---: | ---: | ---: |
| 100 | `$59/mo` | `$168/mo` | `$454/mo` |
| 1,000 | `$588/mo` | `$1,575/mo` | `$4,536/mo` |
| 10,000 | `$5,880/mo` | `$13,650/mo` | `$45,360/mo` |
| 100,000 | `$58,800/mo` | `$115,500/mo` | `$453,600/mo` |

Range assumptions:

- Low: `8` patients/day, `1.5` turns/patient, `30%` cache/offload.
- Baseline: `12` patients/day, `2.5` turns/patient, tiered cache/offload from `20%` to `45%`.
- High: `18` patients/day, `4` turns/patient, `10%` cache/offload.

## Infrastructure And Observability Allowance

AI model spend is only one cost bucket. Production also needs sidecar compute, OpenEMR capacity, database capacity, queueing, cache storage, logs, traces, monitoring, backups, and security operations.

Planning allowance:

| Scale | Suggested non-model allowance | Notes |
| ---: | ---: | --- |
| 100 users | `$100-$500/mo` | Current Railway-style topology, one sidecar, low trace volume |
| 1,000 users | `$500-$2,500/mo` | Sidecar replicas, cache, better log retention, alerting |
| 10,000 users | `$5K-$20K/mo` | Autoscaling, queue workers, centralized observability, database tuning |
| 100,000 users | `$50K+/mo` | Multi-region, enterprise monitoring, compliance operations, vendor support |

These are platform allowances, not model-token prices. At larger scale, support, compliance operations, incident response, audit retention, and vendor contracting become material.

## Architectural Changes By Scale

### 100 Users

- Keep the current three-service topology: OpenEMR, MariaDB, sidecar.
- Keep mock/off modes for rollback and demos.
- Preserve one compose call, one verifier call, and one repair retry max.
- Continue metadata-only tracing by default.
- Use simple per-session response cache and per-user rate limits.

### 1,000 Users

- Add horizontal sidecar replicas.
- Add an OpenEMR-side cache for recent evidence-bundle fingerprints and verified responses with explicit TTL.
- Add request budgets by user, clinic, or tenant.
- Track repair rate and tool-phase rate as first-class cost metrics.
- Add alerts for p95 latency, verifier partial rate, sidecar errors, and daily spend.

### 10,000 Users

- Queue non-urgent summaries and precompute high-value rounding briefs.
- Separate interactive requests from batch/pre-round requests.
- Add centralized trace storage with retention tiers.
- Add cost anomaly detection by tenant, endpoint, model, and response status.
- Consider a cheaper verifier path for simple source-overlap cases while preserving safety behavior.
- Add autoscaling policies tied to queue depth and p95 latency.

### 100,000 Users

- Use enterprise identity, tenant isolation, regional deployment, and strict data residency.
- Negotiate model pricing and support commitments.
- Introduce tenant-level budgets, throttles, and chargeback/showback reporting.
- Split sidecar responsibilities into independent API, worker, eval, and observability services.
- Use queues for all non-interactive work and reserve synchronous capacity for bedside/rounding use.
- Formalize BAA, retention, breach response, and audit export workflows.

## Cost Controls

- Keep evidence bundles bounded and source-selected.
- Prefer deterministic source selection where possible.
- Use repair retries sparingly and track repair rate as a budget signal.
- Keep verifier prompts compact and structured.
- Cache verified answers only within patient, encounter, message, and evidence-bundle fingerprint scope.
- Use mock/off modes for demos, outages, and non-production workflows.
- Keep Langfuse payload capture disabled outside approved environments.
- Alert on daily cost, p95 latency, repair rate, tool-phase rate, and unusually large evidence bundles.

## Current Bottlenecks

Observed Langfuse latency points to three cost/latency drivers:

- Compose response latency is the largest normal model-call component.
- Repair calls materially increase both latency and cost when structured output needs correction.
- Tool phase has the highest average latency and should stay rare unless evals prove it is needed.

The next optimization target is reducing repair frequency and keeping deterministic planner source selection effective. That lowers both cost and p95 latency without weakening the verifier.

## Summary

Actual captured model spend for the current development/demo window is `$0.256832`. Interactive demo traces average about `$0.0035` per paid chat turn, with p95 around `$0.0058`. Using those observed Langfuse numbers, baseline production model cost ranges from roughly `$168/mo` at `100` active clinicians to roughly `$115.5K/mo` at `100K` active clinicians before enterprise discounts, infrastructure, support, and compliance operations.
