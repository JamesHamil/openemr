# AgentForge Eval Results

Current eval target: sidecar mock mode and verifier contract.

Run with:

```shell
/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 agentforge/evals/run_evals.py
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

Latest local run:

```text
passed: 8
failed: 0
```

The runner prints a JSON summary with pass/fail status for each case.
