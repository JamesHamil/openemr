# Week 2 Submission Evidence

## Claim

AgentForge includes PR-blocking eval CI and an observable deployed demo for the Week 2 Clinical Co-Pilot submission.

This maps to the Week 2 assignment requirement for an eval-driven CI gate: a 50-case golden set, boolean rubric categories including `schema_valid`, `citation_present`, `factually_consistent`, `safe_refusal`, and `no_phi_in_logs`, and a build failure when a category drops below threshold or regresses by more than 5%.

## Eval-Driven CI Gate

Evidence:

- Golden set: [`agentforge/evals/week2_cases.json`](../../agentforge/evals/week2_cases.json) contains exactly 50 synthetic/demo cases.
- Runner: [`agentforge/evals/run_week2_evals.py`](../../agentforge/evals/run_week2_evals.py) executes extraction and chat cases through the sidecar path.
- Shared gate: [`agentforge/evals/enforce_week2_gate.py`](../../agentforge/evals/enforce_week2_gate.py) enforces the case count, required rubrics, pass threshold, and baseline regression rule.
- Baseline: [`agentforge/evals/week2_baseline.json`](../../agentforge/evals/week2_baseline.json) stores saved category pass rates for regression checks.
- PR workflow: [`.github/workflows/agentforge-week2-evals.yml`](../../.github/workflows/agentforge-week2-evals.yml) runs on pull requests that touch AgentForge code, the document viewer template, or the workflow itself.
- Git hook: [`.githooks/pre-push`](../../.githooks/pre-push) runs sidecar unit tests, the 50-case Week 2 eval runner, and the shared gate before push when `core.hooksPath=.githooks` is configured.

Required boolean rubrics:

- `schema_valid`
- `citation_present`
- `factually_consistent`
- `safe_refusal`
- `no_phi_in_logs`

Additional Week 2 rubrics:

- `supervisor_route_present`
- `expected_worker_handoff`
- `guideline_metadata_present`

Gate behavior:

- Fails if the golden set does not contain exactly 50 cases.
- Fails if any case fails.
- Fails if any rubric pass rate is below `0.95`.
- Fails if any rubric regresses by more than `0.05` from the saved baseline.

Latest local verification:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=agentforge/sidecar agentforge/sidecar/.venv/bin/python agentforge/evals/run_week2_evals.py --json

cases: 50
passed: 50
failed: 0
schema_valid: 50/50
citation_present: 50/50
factually_consistent: 50/50
safe_refusal: 50/50
no_phi_in_logs: 50/50
```

Cost and latency evidence is summarized in [`COST_LATENCY_REPORT.md`](COST_LATENCY_REPORT.md), including actual development/demo model spend, projected production model cost, p50/p95 latency, and bottleneck analysis.

To make the workflow hard PR-blocking in GitHub, mark `AgentForge Week 2 Evals / week2-evals` as a required status check in branch protection. The repository contains the blocking check, gate logic, and pre-push git hook; GitHub branch protection is the repository setting that makes a required check unmergeable when it fails.

## Observable Deployed Demo

The deployed demo is demo-data-only and keeps OpenEMR as the clinical trust boundary.

Observable surfaces:

- OpenEMR document viewer shows extracted structured facts, citations, and document preview highlights.
- Clinical Co-Pilot response debug trace shows supervisor route, graph nodes, worker handoffs, guideline retrieval metadata, provider diagnostics, and warnings.
- Sidecar traces include timing, token/cost metadata when available, selected source counts, source-selection mode, verifier result, repair count, and PHI-safe identifiers.
- Railway runs the OpenEMR and AgentForge sidecar services for the deployed demo.
- Langfuse can receive PHI-safe metadata traces when enabled; raw PHI, document text, screenshots, and full images are not logged by default.
