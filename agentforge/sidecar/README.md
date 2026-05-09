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

`AGENTFORGE_SIGNING_SECRET` is required for `/v1/chat`; the sidecar rejects signed chat requests when it is not configured.

## Latency Controls

The real-mode answer path defaults to fast local evidence selection plus model composition. It only uses model tool-planning or model verification when the automatic policy needs escalation.

```text
AGENTFORGE_SOURCE_SELECTION_MODE=auto        # auto | deterministic | model
AGENTFORGE_VERIFY_MODE=auto                  # auto | deterministic | model
AGENTFORGE_COMPOSE_MODEL=gpt-5-nano          # optional, defaults to AGENTFORGE_OPENAI_MODEL
AGENTFORGE_VERIFY_MODEL=gpt-5-nano           # optional, defaults to AGENTFORGE_OPENAI_MODEL
AGENTFORGE_RESPONSE_CACHE_ENABLED=false      # optional in-memory cache for repeated bundle/question pairs
AGENTFORGE_RESPONSE_CACHE_TTL_SECONDS=120
```

## Langfuse Observability

Langfuse tracing is optional and disabled by default. Metadata-only tracing is the default when enabled; raw user messages, chart evidence, prompts, model outputs, and answers are not sent unless payload capture is explicitly enabled.

```text
AGENTFORGE_LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=production
AGENTFORGE_LANGFUSE_TAGS=openemr,clinical-copilot
AGENTFORGE_LANGFUSE_CAPTURE_PAYLOADS=false
```

Use `AGENTFORGE_LANGFUSE_CAPTURE_PAYLOADS=true` only in an approved environment where sending request/response payloads to Langfuse is acceptable. For short-lived jobs, `AGENTFORGE_LANGFUSE_FLUSH_AT_END=true` forces a flush after each `/v1/chat` request; leave it off for normal long-running FastAPI workers.

## Tests

```shell
PYTHONPATH=agentforge/sidecar agentforge/sidecar/.venv/bin/python -m unittest discover -s agentforge/sidecar/tests
PYTHONPATH=agentforge/sidecar agentforge/sidecar/.venv/bin/python agentforge/evals/run_evals.py
```

Set `AGENTFORGE_EVAL_MODE=live` to run the smoke evals through real mode with OpenAI credentials. The default remains deterministic mock mode for local and CI runs.
