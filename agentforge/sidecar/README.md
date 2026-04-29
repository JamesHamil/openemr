# AgentForge Sidecar

FastAPI sidecar for the Clinical Co-Pilot.

## Modes

- `AGENTFORGE_MODE=mock`: deterministic contract-valid responses for demos and rollback.
- `AGENTFORGE_MODE=real`: OpenAI structured-output path when dependencies and `OPENAI_API_KEY` are configured.
- `AGENTFORGE_MODE=off`: controlled unavailable response.

## Local Run

```shell
cd agentforge/sidecar
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn agentforge_sidecar.app:app --host 0.0.0.0 --port 8000
```

The OpenEMR module expects:

```text
AGENTFORGE_SIDECAR_URL=http://sidecar-host:8000
AGENTFORGE_SIGNING_SECRET=<shared secret>
```

## Tests

```shell
PYTHONPATH=agentforge/sidecar python3 -m unittest agentforge.sidecar.tests.test_verifier
python3 agentforge/evals/run_evals.py
```
