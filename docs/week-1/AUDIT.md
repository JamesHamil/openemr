# AgentForge Final Audit

## Executive Summary

This audit reviews the AgentForge Clinical Co-Pilot as a demo-data submission built inside the OpenEMR fork. The system follows a conservative clinical-AI pattern: OpenEMR remains the trust boundary and source of record, while the AgentForge sidecar performs bounded orchestration, structured response handling, source-support verification, tracing, and eval execution.

The current implementation is organized around a read-only rounding workflow. A physician opens a patient chart in OpenEMR, submits a question from the AgentForge module, and OpenEMR assembles a minimum-necessary `RoundingContextBundle` from authorized chart records. The sidecar receives only that signed, short-lived bundle and returns a verified, partial, refused, or failed response with citations, warnings, blocked claims, and a trace ID.

The audit posture is intentionally submission-focused: the project demonstrates the core control design for authentication, authorization, PHI minimization, bounded evidence, verification, observability, and compliance gating. Real PHI and production clinical operation remain behind institutional compliance approval, vendor contracting, deployment hardening, and retention-policy review.

## Security Audit

### Authentication And Session Boundary

OpenEMR owns authentication, browser session state, selected patient context, encounter context, CSRF protection, and user identity. The AgentForge browser panel is a patient-context feature, and the module endpoint validates the active session before constructing any sidecar request.

### Authorization Controls

The module uses OpenEMR ACL checks before it gathers evidence. Patient IDs supplied by the browser are treated as UI continuity data and are checked against the active OpenEMR session. The sidecar receives hashed user, patient, and encounter scope values plus a bundle ID; it does not receive OpenEMR credentials, direct database access, or delegated chart-retrieval authority.

### Sidecar Request Protection

Module-to-sidecar requests are signed with `AGENTFORGE_SIGNING_SECRET`. The sidecar verifies the HMAC signature, validates the request schema, and enforces short-lived `expires_at` values with a bounded clock-skew allowance. Missing signing configuration fails closed on both the module and sidecar paths.

### Data Exposure Controls

The evidence bundle is the PHI control surface. OpenEMR sends bounded source records rather than a whole chart export, and the sidecar uses only the supplied bundle. Browser code never receives the signing secret or OpenAI API key. Optional Langfuse tracing is metadata-only by default; raw messages, source values, prompts, model outputs, and answers are captured only when explicitly enabled for an approved environment.

### Prompt And Model Safety

Chart text is treated as untrusted evidence. The sidecar detects instruction-like text in retrieved notes, keeps it inside the patient-record context, and surfaces a warning. The verifier blocks unsupported factual claims, removes unsupported source displays, preserves adapter-gap warnings, and refuses treatment-directive prompts that ask the agent to start, stop, prescribe, hold, administer, or otherwise direct care.

## Performance Audit

### Latency Model

The workflow is latency-sensitive because the user is preparing for rounds. The implementation favors a first useful verified response over exhaustive chart retrieval. OpenEMR collectors query bounded, high-signal surfaces first: patient snapshot, active problems, allergies, medications, vitals, labs, and recent notes.

### Collector Shape

Collectors use small limits and recent-first ordering. The evidence bundle carries `adapter_status` entries with per-adapter state and latency fields, allowing the sidecar and UI to show partial results when a category is unavailable or delayed.

### Sidecar Runtime

The sidecar supports `mock`, `real`, and `off` modes. Mock mode is deterministic for demos and evals. Real mode uses OpenAI structured outputs behind a provider abstraction and records operational timing fields such as planning latency, compose latency, total latency, selected source count, token estimates, and cost estimates.

### Response Controls

Verification remains on the critical path. A response can be `verified` only when supported claims, source IDs, source values, adapter status, and warning conditions align. Partial responses are first-class outputs, so the system can stay usable while still preserving source-support constraints.

## Architecture Audit

### System Organization

AgentForge is implemented inside the OpenEMR fork with a clear runtime split:

- `interface/modules/custom_modules/agentforge/`: OpenEMR module UI, module endpoint, CSRF/session checks, ACL checks, rate limiting, evidence collection, sidecar signing, response cache, and audit event.
- `agentforge/sidecar/`: FastAPI sidecar, request validation, model-provider abstraction, deterministic mock provider, real OpenAI provider, verifier, observability, and tests.
- `agentforge/evals/`: synthetic evidence-bundle smoke cases and eval runner.
- `agentforge/contracts/`: request and response schema contracts.

### Data Flow

1. The physician opens a patient chart in OpenEMR.
2. The AgentForge module confirms session, CSRF token, ACL, patient context, and rate limit.
3. OpenEMR collectors assemble a bounded `RoundingContextBundle`.
4. OpenEMR signs the request and sends it to the sidecar over internal networking.
5. The sidecar validates signature, schema, and expiration.
6. The sidecar produces a structured answer through mock or real mode.
7. The verifier filters unsupported claims and adds warnings.
8. OpenEMR records an audit event with the sidecar trace ID and renders the answer, sources, warnings, and trace status.

### Integration Points

New capabilities should attach to the same pattern: add an OpenEMR-owned evidence adapter, extend the bundle contract only when needed, update verifier behavior, add eval coverage, and expose the result through the existing module response renderer. The sidecar remains a transformation and verification boundary, not a second data authority.

### Deployment Shape

Railway runs OpenEMR, MariaDB, and `agentforge-sidecar` as separate services. OpenEMR reaches the sidecar over private networking. The sidecar has its own Dockerfile and Railway config, and the OpenEMR module can degrade to a controlled unavailable response when the sidecar path is not available.

## Data Quality Audit

### Evidence Completeness

The current evidence bundle represents a focused chart snapshot rather than a full inpatient chart. It captures the categories needed for the initial rounding use case and marks each category with an adapter status. This lets the assistant distinguish retrieved facts from retrieval gaps.

### Consistency And Normalization

Collectors normalize source records into stable fields: `id`, `record_type`, `recorded_at`, `field_path`, `value`, optional `note_span`, and optional metadata. This creates a consistent verifier surface across problems, allergies, medications, vitals, labs, notes, and demographics even though OpenEMR stores those records in different tables and workflows.

### Reliability Controls

The sidecar does not infer chart absence from missing source rows. Adapter status is the carrier for unavailable categories, partial retrieval, and collector failures. Negative observations, such as no active allergy records in retrieved lists, are represented as retrieval status rather than synthetic chart evidence.

### Eval Coverage

The eval suite uses synthetic evidence bundles shaped like the production contract. Cases cover complete chart briefs, missing labs, lab abnormalities, conflicting notes, unsupported citations, unauthorized patient context, collector failure, treatment-directive refusal, prompt injection in notes, question-specific uncertainty, and physician-style prompts for allergies, cardiac issues, metabolic risk, oncology history, red flags, medication reconciliation, first-room questions, and missing data.

## Compliance And Regulatory Audit

### HIPAA-Relevant Boundary

OpenEMR remains the patient-linked system of record and audit authority. The sidecar receives minimum-necessary evidence for a single authorized patient context and keeps operational traces PHI-safe by default. The public deployment is maintained as a demo-data environment.

### Audit Logging

OpenEMR records an `agentforge-chart-brief` audit event with user, patient, success state, response status, and sidecar trace ID. The sidecar trace includes operational metadata such as request ID, conversation ID, mode, source count, adapter statuses, blocked-claim count, token estimates, cost estimates, latency, warning state, and error state.

### Data Retention

The module uses short-lived session response caching with a bounded TTL and entry count. Sidecar telemetry is metadata-only by default. Any production retention schedule should keep OpenEMR as the durable audit record and treat sidecar traces as operational logs with defined retention, access review, and deletion controls.

### Vendor And BAA Posture

OpenAI and optional Langfuse remain server-side integrations. Real PHI use requires institutional approval, vendor review, BAA coverage where applicable, retention policy alignment, and explicit configuration for payload capture, redaction, and trace storage.

### Breach And Incident Readiness

The production path should connect AgentForge events to the organization’s incident response, breach notification, access review, key rotation, backup, retention, and rollback procedures. The current implementation already preserves the key architectural control: OpenEMR stays accountable for clinical access while the sidecar remains a bounded, observable AI runtime.

## Final Submission Alignment

- The project is read-only for the initial capability.
- OpenEMR owns authentication, authorization, patient context, evidence gathering, and clinical audit events.
- The sidecar receives signed, short-lived, minimum-necessary evidence bundles.
- Verification is bounded source-support plus warning surfacing.
- Adapter status carries missing, unavailable, partial, and failed collector state.
- Demo operation and synthetic evals are supported.
- Real PHI and production clinical use remain behind compliance and deployment gates.
