# AgentForge Eval Results

Current default eval target: deterministic sidecar mode and verifier contract. Set `AGENTFORGE_EVAL_MODE=live` to run the same fixtures through real mode with OpenAI credentials.

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

The runner prints a JSON summary with pass/fail status for each case.
