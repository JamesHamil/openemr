# AgentForge Clinical Co-Pilot PRD

## Summary

AgentForge Clinical Co-Pilot is a read-only, hospitalist-focused assistant embedded in OpenEMR. It helps a physician preparing for inpatient rounds generate a source-backed chart brief for the selected patient and ask patient-scoped follow-up questions. The product is scoped to OpenEMR patient context, bounded evidence, and clinician-reviewed decision support.

The project follows the direction established in `AUDIT.md`, `USERS.md`, and `ARCHITECTURE.md`: OpenEMR remains the clinical trust boundary, while an in-repo FastAPI sidecar handles LLM orchestration, structured responses, verification, evals, and PHI-safe operational traces.

The implementation remains demo-data-only until separate compliance gates are satisfied.

## Product Requirements

- Target user: hospitalist preparing for inpatient rounds.
- Primary workflow: selected patient in OpenEMR -> Clinical Co-Pilot panel -> chart brief -> follow-up questions about that same patient.
- Core capabilities:
  - Generate a pre-round chart brief for the selected patient.
  - Answer patient-scoped follow-up questions using bounded evidence.
  - Display citations, warnings, and verification status.
  - Refuse treatment directives and unauthorized or ungrounded requests.
- Product boundaries:
  - Demo and synthetic patient data for the current checkpoint.
  - Read-only chart synthesis.
  - Single-patient OpenEMR context.
  - Embedded OpenEMR workflow.
  - Production HIPAA readiness through a separate compliance gate.

## Implementation Requirements

- OpenEMR module:
  - Lives at `interface/modules/custom_modules/agentforge/`.
  - Provides a patient-context panel and module-local chat endpoint.
  - Performs CSRF, session, patient context, ACL, rate-limit, and audit checks before sidecar calls.
  - Builds the evidence bundle inside OpenEMR. The sidecar never fetches or authorizes chart data.
- Sidecar:
  - Lives at `agentforge/sidecar/`.
  - Exposes `/healthz` and `/v1/chat`.
  - Supports `real`, `mock`, and `off` modes.
  - Uses OpenAI in real mode through server-side configuration.
  - Returns deterministic contract-valid responses in mock mode.
  - Returns controlled unavailable output in off mode.
- Contracts:
  - Live under `agentforge/contracts/`.
  - Define `agentforge.request.v1`, `agentforge.response.v1`, `RoundingContextBundle`, claims, sources, warnings, and response statuses.
- Verification:
  - Every factual clinical claim must cite source IDs plus supporting field paths, values, or note spans, except explicit missing-data claims supported by adapter status.
  - Unsupported claims are blocked, rewritten as uncertainty, or refused.
  - General clinician confirm/review guidance may appear in prose or warnings, but is not treated as a verified factual claim unless directly source-supported.
  - Prompt injection inside chart text is treated as untrusted record content.
- Observability:
  - OpenEMR records a patient-linked audit event with the sidecar trace ID.
  - Sidecar traces remain PHI-safe by default and include collector status, latency, mode, token/cost estimates, verification status, blocked claims, and error state.
- Deployment:
  - Railway runs OpenEMR, MariaDB, and the sidecar as separate services from the same fork.
  - Server-side configuration includes sidecar URL, required signing secret, OpenAI API key, model config, and `AGENTFORGE_MODE`.
  - Rollback is disabling the module or switching `AGENTFORGE_MODE=off` or `mock`.

## Acceptance Criteria

- OpenEMR exposes a Clinical Co-Pilot patient menu entry.
- The panel works only with an active patient context.
- The module endpoint accepts a CSRF-protected chat request and returns a contract-valid response.
- The sidecar `/healthz` endpoint reports mode and service health.
- The sidecar `/v1/chat` endpoint returns `verified`, `partial`, `refused`, or `failed`.
- Mock mode can produce a source-backed chart brief without external services.
- Real mode is wired for OpenAI structured output when dependencies and keys are configured.
- The verifier blocks unsupported claims and treatment directives.
- Eval smoke tests cover happy path, missing data, conflicting data, unsupported citation, unauthorized patient, collector failure, unsafe treatment request, and prompt injection.
- OpenEMR remains usable when the sidecar is unavailable.
- `AUDIT.md` covers the security, performance, architecture, data quality, and compliance/regulatory audit passes for the final submission.

## Delivery Artifacts

- `PRD.md`: execution source of truth.
- `agentforge/contracts/`: schemas, examples, and contract documentation.
- `agentforge/sidecar/`: FastAPI sidecar, verifier, providers, and tests.
- `agentforge/evals/`: eval dataset, runner, and current results.
- `interface/modules/custom_modules/agentforge/`: OpenEMR module shell and chat endpoint.
- Updated project docs that reflect implementation status without claiming production HIPAA readiness.

## Assumptions

- The architecture direction is settled: hospitalist + OpenEMR trust boundary + in-repo FastAPI sidecar + bounded evidence bundle + verification.
- OpenAI is the real-mode provider, but model selection stays configurable and makes no medical safety claim.
- Real mode must retain mock/off fallback for demos, failures, and rollback.
- Development and deployment remain demo-data-only until compliance gates are met.
- Synthea C-CDA sample patients remain the recommended realistic sample-data path.
