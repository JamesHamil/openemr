# AgentForge MVP Audit

## Executive Summary

This audit was performed before implementing the Clinical Co-Pilot AI layer. The main finding is that OpenEMR already provides many of the primitives a trustworthy clinical agent needs, but those primitives must remain inside OpenEMR's trust boundary. Authentication, session management, patient context, role-based permissions, audit logs, and clinical data storage are already part of the EHR. The AI integration should therefore avoid becoming a second EHR, a parallel database, or an external chatbot that independently retrieves and stores patient data.

The most important security risk is over-disclosure of Protected Health Information. A model integration that sends broad chart history, raw notes, or unfiltered patient records to an LLM provider would create unnecessary exposure and make auditability difficult. The safer pattern is a minimum-necessary evidence bundle assembled by OpenEMR after session, CSRF, patient, encounter, and ACL validation. The sidecar should receive only that bounded bundle, should not have OpenEMR database credentials, and should not be able to call back for additional chart data.

The most important reliability risk is unsupported clinical claims. In this domain, a fluent answer is not enough; every factual statement must trace back to a specific chart source. A citation label alone is also not enough, because a model can cite a real source that does not support the sentence. The verification layer must check source IDs, record types, field paths or note spans, extracted values, and timestamps before a response reaches the physician.

Performance risk is real because the user workflow is time-sensitive. A hospitalist preparing for rounds may have less than two minutes before entering a patient room. However, speed cannot come from skipping verification. The MVP architecture should optimize for a first useful verified response, with explicit warnings when collectors are unavailable or data is missing, stale, or conflicting.

The data quality audit shows that OpenEMR's data is broad and clinically rich, but not uniformly normalized for AI summarization. Notes, medications, labs, allergies, vitals, problems, encounters, documents, and orders live in different parts of the application and may have different completeness, recency, and formatting. Missing fields and stale records are not edge cases; they are expected clinical realities and must be surfaced in the assistant's output.

The compliance conclusion is that the MVP should remain demo-data-only and should not claim production HIPAA readiness. Real PHI use would require vendor BAAs, retention policy, breach response procedures, access review, logging controls, and a stronger deployment posture. The MVP can still be valuable if it proves the safe foundation: OpenEMR-owned authorization, bounded evidence retrieval, source-bound verification, visible failure modes, and audit-aware design.

## Security Audit

- OpenEMR is the correct authority for login, session state, patient context, ACL checks, and audit events.
- The browser must never call the LLM provider directly and must never receive API keys or sidecar signing secrets.
- Patient and encounter IDs supplied by the UI must be treated as hints only; the server must validate them against the active OpenEMR session and permissions.
- The sidecar must not receive database credentials, OpenEMR API tokens, or delegated tool permissions.
- Chart text must be treated as untrusted input. Prompt injection inside notes cannot override system policy, authorization rules, or verification requirements.
- Demo data only is acceptable for MVP. Real PHI requires a separate compliance review before any external LLM or third-party tracing is used.

## Performance Audit

- The target workflow is latency-sensitive: a hospitalist preparing for rounds needs useful context quickly.
- OpenEMR contains multiple data surfaces, so exhaustive chart retrieval can be slower than the clinical moment allows.
- The MVP should prioritize bounded, high-signal evidence for the first answer: demographics, active problems, allergies, current medications, recent notes, recent labs, vitals, and visible adapter gaps.
- Verification is non-negotiable and should not be skipped for speed.
- Collector timeouts should produce a partial verified answer with warnings rather than silent omission.

## Architecture Audit

- OpenEMR is a large PHP application with established module patterns under `interface/modules/custom_modules/`.
- Existing APIs, services, controllers, and database tables should be reused where practical instead of creating a second clinical data model.
- The AgentForge module should live inside the OpenEMR fork and act as the trusted gateway for user requests.
- The AI sidecar should also live inside the fork but run as a separate runtime boundary for model orchestration, structured output handling, verification, evals, and operational tracing.
- The clean integration point is an OpenEMR module-local endpoint that validates the request, builds a bounded evidence bundle, signs it, and sends it to the sidecar.

## Data Quality Audit

- OpenEMR data is clinically rich but distributed across many record types and workflows.
- Notes may contain useful context but are free text and must be bounded before model use.
- Medication, allergy, problem, lab, and vital records may differ in recency and completeness.
- Missing fields, duplicate records, stale data, and conflicting notes are expected and should be represented as warnings or uncertainty.
- The evidence bundle should record adapter status so the assistant can distinguish "not retrieved" from "not present in the chart."

## Compliance And Regulatory Audit

- PHI handling affects storage, transmission, logging, retention, and access control.
- The MVP must not use real PHI and must not claim production HIPAA readiness.
- Before real PHI use, LLM and telemetry providers would need appropriate contractual coverage, including BAA considerations.
- Logs and traces must avoid raw chart text by default. Operational traces should use hashes, bundle IDs, trace IDs, latencies, token counts, and verification statuses.
- OpenEMR should remain the patient-linked audit system. The sidecar should maintain only PHI-safe operational traces.
- A production version would need documented incident response, breach notification process, access review, backup/retention policy, and rollback procedures.
