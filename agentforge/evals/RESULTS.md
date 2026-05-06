# AgentForge Eval Results

Testing philosophy and examples are documented in [`EVALS.md`](EVALS.md).

Current Week 1 eval target: deterministic sidecar mode and verifier contract. Set `AGENTFORGE_EVAL_MODE=real` to run the same fixtures through OpenAI-backed real mode with server-side credentials.

Run with:

```shell
PYTHONPATH=agentforge/sidecar python3 agentforge/evals/run_evals.py
```

The default output is a readable scorecard with each case's input, output, expected status, actual status, failure reasons, warnings, source types, blocked-claim count, and pass/fail result.

Mock mode keeps strict phrase-based assertions for deterministic regression testing. Live mode uses concept checks for model-written clinical prose so wording variability does not fail an otherwise supported answer.

For machine-readable output:

```shell
PYTHONPATH=agentforge/sidecar python3 agentforge/evals/run_evals.py --json
```

Smoke cases:

- complete chart brief
- missing labs
- conflicting notes
- unsupported citation
- unauthorized patient
- collector failure
- unsafe treatment request
- prompt injection in chart text
- physician prompt families for allergies, cardiac, endocrine/metabolic, oncology, red flags, med rec, allergy-risk meds, first-room questions, and missing-data questions

Latest local run:

```text
passed: 22
failed: 0
```

Week 2 multimodal runner:

```shell
PYTHONPATH=agentforge/sidecar python3 agentforge/evals/run_week2_evals.py
```

Machine-readable Week 2 output:

```shell
PYTHONPATH=agentforge/sidecar python3 agentforge/evals/run_week2_evals.py --json
```

Latest Week 2 local run:

```text
passed: 50
failed: 0
schema_valid: 50/50
citation_present: 50/50
factually_consistent: 50/50
safe_refusal: 50/50
no_phi_in_logs: 50/50
supervisor_route_present: 50/50
expected_worker_handoff: 50/50
guideline_metadata_present: 50/50
p50: 0.00s
p95: 0.00s
```

The Week 2 dataset is visible at [`week2_cases.json`](week2_cases.json). The saved regression baseline is [`week2_baseline.json`](week2_baseline.json), and CI fails on failed cases, rubric pass rates below threshold, or more than 5% rubric regression from baseline.
