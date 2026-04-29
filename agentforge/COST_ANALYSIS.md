# AgentForge AI Cost Analysis

## Summary

Cost is tracked per request, not estimated only as token price multiplied by users. Clinical usage depends on patients rounded per day, number of follow-up questions, collector coverage, cache hit rate, model choice, retries, and trace retention.

The first implementation uses one primary OpenAI structured-output call plus at most one schema-repair retry. Mock and off modes cost no model tokens and remain available for demos, rollback, and development.

## Baseline Request Shape

- One chart brief request per selected patient.
- Zero to three follow-up questions per patient.
- Bounded evidence bundle rather than full chart history.
- No multi-agent fanout.
- No model-side retrieval.
- No separate judge model in the first slice.

## Scale Scenarios

| Scale | Expected Shape | Cost Controls | Architecture Changes |
| --- | --- | --- | --- |
| 100 users | Single OpenEMR service, MariaDB, single sidecar, demo-data traces | request caps, mock/off fallback, one retry max | none beyond current sidecar deployment |
| 1,000 users | More concurrent rounding sessions and repeated patient summaries | cache recent OpenEMR-built patient snapshots, stricter per-user limits | add sidecar replicas and OpenEMR-side cache with retention limits |
| 10,000 users | Hospital-system usage with many repeated morning summaries | queue non-urgent summaries, reuse evidence bundle summaries, monitor cost anomalies | centralize operational traces and add workload queues |
| 100,000 users | Enterprise, multi-region, formal compliance posture | negotiated model pricing, retention controls, per-tenant budgets | enterprise identity, regional data controls, formal incident response, signed BAAs |

## Required Metrics

Each sidecar trace records mode, model, estimated input tokens, estimated output tokens, source count, collector count, retry count, verification status, latency, and estimated cost. Production cost analysis must be based on those observed traces plus projected patient volume.
