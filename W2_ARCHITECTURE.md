# Week 2 Architecture Defense: Multimodal Evidence Agent

## Executive Summary

Week 2 expands AgentForge Clinical Co-Pilot from a structured OpenEMR chart-brief assistant into a multimodal evidence agent. Week 1 already established the core safety pattern: OpenEMR owns authentication, patient context, authorization, evidence collection, audit logging, and sidecar request signing; the sidecar transforms a bounded evidence bundle into a source-backed response and verifies claims before display.

The Week 2 architecture keeps that trust boundary intact while adding two carefully scoped capabilities: the agent can read real-world clinical documents, and it can route work across a small, inspectable LangGraph worker graph. The implementation target is intentionally narrow: one lab PDF, one intake form, one guideline corpus, one supervisor, two required workers, and a 50-case eval gate.

This is not a general medical-document platform. It is a controlled expansion of the Week 1 clinical workflow for a physician preparing for follow-up or rounds: identify what changed, what deserves attention, and which patient-record or guideline source supports the answer.

## Week 1 Baseline Vs Week 2 Expansion

Week 1 baseline behavior:

- OpenEMR builds a bounded `RoundingContextBundle` from structured chart data.
- The module sends a signed, short-lived request to the sidecar.
- The sidecar composes a response using selected evidence only.
- The verifier checks that factual clinical claims are supported by known source records.
- The UI displays answer text, citations, warnings, and trace ID.
- Smoke evals cover chart summaries, missing data, unsafe requests, and verifier behavior.

Week 2 expansion:

- Add OpenEMR Documents-based extraction for `lab_pdf` and `intake_form`.
- Store source documents in OpenEMR Documents.
- Persist extracted facts in module-owned traceable records.
- Add strict extraction schemas with source citation fields.
- Add visual document citation metadata, including page-relative bounding boxes.
- Add guideline retrieval with sparse search, dense embeddings, and local rerank.
- Add a LangGraph supervisor graph with `intake-extractor` and `evidence-retriever` workers, plus answer and critic/verifier nodes around the existing Week 1 logic.
- Add a 50-case boolean eval gate that blocks regressions.

The main design constraint is unchanged: the sidecar may transform scoped evidence, but it must not become a second EHR, bypass OpenEMR authorization, or invent clinical facts.

## Document Ingestion Architecture

Document ingestion starts in OpenEMR Documents because OpenEMR is the clinical system of record and the patient-context authority. A clinician uploads or manages files through the native patient Documents workflow first. AgentForge then selects an existing patient document through a CSRF-protected module endpoint and validates session, patient context, ACLs, file type, size limits, and declared document type before any sidecar call.

The source file remains stored through OpenEMR’s existing Documents subsystem. The module records an AgentForge document row that links the OpenEMR document ID, patient ID, encounter ID when present, document type, content hash, extraction status, and timestamps. This preserves OpenEMR document integrity and avoids creating a parallel file store.

Derived facts are persisted in module-owned traceable tables for the Week 2 demo rather than being written directly into core clinical tables such as `procedure_result`, `lists`, or `prescriptions`. That tradeoff is deliberate. It makes extracted facts visible, auditable, and citable without pretending they are clinician-entered chart facts or risking duplicate clinical records. Facts are only returned as active evidence while the linked OpenEMR document still exists, belongs to the active patient, and is not deleted. A later production version could promote reviewed extracted facts into FHIR resources or OpenEMR records through a clinician-confirmed workflow.

Supported document types:

- `lab_pdf`: lab result PDF stored in OpenEMR Documents.
- `intake_form`: patient intake form with demographics, chief concern, medications, allergies, and family history.

If document retrieval, extraction, or schema validation fails, the system returns a visible partial status with adapter warnings. It does not silently omit the document or convert low-confidence extraction into chart truth.

## Extraction And Citation Contract

Extraction is schema-first. The model does not answer directly from the OpenEMR document. It extracts structured facts into strict schemas, and those schemas require source citation metadata.

Required lab fields:

- test name;
- value;
- unit;
- reference range;
- collection date;
- abnormal flag;
- source citation.

Required intake fields:

- demographics fields;
- chief concern;
- current medications;
- allergies;
- family history;
- source citation.

Minimum citation shape:

```json
{
  "source_type": "lab_pdf",
  "source_id": "openemr-document-123",
  "page_or_section": "page 1",
  "field_or_chunk_id": "lab-result-potassium",
  "quote_or_value": "Potassium 5.6 mmol/L",
  "bounding_box": {
    "page": 1,
    "x": 0.12,
    "y": 0.34,
    "width": 0.42,
    "height": 0.05
  }
}
```

Bounding boxes are page-relative coordinates so the UI can render a simple overlay on a PDF preview without storing model-specific geometry. If a document is text-native and a bounding box is unavailable, the system still requires page or section plus quote/value metadata and marks the visual overlay unavailable.

Every final clinical claim must cite patient-record evidence, guideline evidence, or both. Patient-record facts and guideline evidence are intentionally separated. A guideline can support general clinical context, but it cannot prove that this patient has a medication, allergy, lab value, diagnosis, or symptom.

Unsupported extracted facts are not hidden. They are either rejected by schema validation, marked low-confidence, or surfaced as warnings so the physician knows what needs manual review.

## Hybrid Guideline RAG

The Week 2 guideline corpus is intentionally small and local. It should cover the demo’s likely primary-care and follow-up topics: abnormal labs, diabetes and prediabetes, lipids, hypertension, medication review, allergy review, and red-flag follow-up. The corpus is committed as curated chunks with source metadata rather than fetched dynamically at answer time.

Retrieval uses a hybrid strategy:

- sparse keyword scoring for exact clinical terms;
- OpenAI embeddings for semantic similarity;
- local weighted rerank over the combined candidate set.

This avoids adding a separate Cohere key for the Week 2 core build while still satisfying the architectural requirement for keyword plus dense retrieval and reranking. A Cohere adapter can be added later behind the same interface if the project needs stronger rerank behavior.

Only top grounded guideline snippets are passed to the answer model. The retriever returns source metadata for each chunk, including guideline title, section, chunk ID, URL or citation label, and quote text. The final composer receives patient evidence and guideline evidence as different source types and must preserve that distinction in the citation metadata.

## Supervisor And Worker Graph

Week 2 adds a small inspectable LangGraph flow rather than a broad autonomous agent network. The required agent shape has one supervisor and two core workers:

- `intake-extractor`: handles document extraction, strict schema validation, citation metadata, confidence, and extraction warnings.
- `evidence-retriever`: handles guideline query construction, hybrid retrieval, rerank, and grounded snippet selection.

The implemented chat graph is:

```text
START -> supervisor -> evidence_retriever -> answer_worker -> critic_verifier -> END
```

The implemented document graph is:

```text
START -> supervisor -> intake_extractor -> END
```

The `answer_worker` wraps the existing mock/real answer provider. The `critic_verifier` wraps the existing Week 1 verifier as the final gate. The supervisor handles route decisions, authorization refusal, treatment-directive refusal, and off-mode fallback before model work. Each handoff records:

- route decision;
- route reason;
- worker input summary;
- worker output status;
- latency;
- selected source or citation IDs;
- warnings or failure state.

The supervisor is not allowed to bypass the Week 1 evidence contract. It can choose workers and assemble context, but the existing verifier remains the final gate before the answer reaches the UI. If the graph produces uncited claims, unsupported extracted facts, or unsafe treatment directives, the verifier blocks or downgrades the response.

## Trust Boundaries And PHI Controls

The trust model stays centered on OpenEMR:

| Boundary | Control |
| --- | --- |
| Browser to OpenEMR | Session validation, CSRF, ACL checks, active patient context, selected-document validation |
| OpenEMR to document storage | OpenEMR Documents subsystem, patient association, content hash, audit trail |
| OpenEMR to sidecar | Signed short-lived requests, bounded payloads, server-side secrets |
| Sidecar to LLM | Minimum necessary evidence, no database credentials, no OpenEMR API token |
| Sidecar to observability | PHI-safe metadata only by default |
| LLM to physician | Strict schemas, citation contract, verifier, warnings, refusals |

Raw PHI, full document text, screenshots, and document images must not be sent to SaaS observability tools. Traces should use hashes, IDs, status codes, latencies, token counts, retrieval counts, confidence values, and rubric outcomes. The deployed project remains demo-data-only until institutional compliance review, BAA coverage, retention policy, and incident-response procedures are in place.

## Eval-Driven CI Gate

The Week 2 hard gate is eval-driven CI. A working demo is not sufficient if regressions can reach the demo unnoticed.

The Week 2 golden set contains 50 synthetic or demo cases that exercise:

- lab PDF extraction;
- intake form extraction;
- schema validation;
- citation presence;
- factual consistency;
- guideline retrieval;
- unsafe request refusal;
- missing-data behavior;
- PHI-safe logging.

Boolean rubric categories:

- `schema_valid`;
- `citation_present`;
- `factually_consistent`;
- `safe_refusal`;
- `no_phi_in_logs`;
- `supervisor_route_present`;
- `expected_worker_handoff`;
- `guideline_metadata_present`.

The CI workflow at `.github/workflows/agentforge-week2-evals.yml` fails if the suite does not contain exactly 50 cases, if any case fails, if any category drops below its pass threshold, or if any category regresses by more than 5% from the saved baseline. This is designed to satisfy the grading gate where a small introduced regression must cause the eval suite to fail.

The eval output should be machine-readable JSON and human-readable summary text. Each failure should include the case ID, failed rubric category, expected behavior, actual behavior, and trace ID.

## Observability, Cost, And Latency

Week 2 traces extend the Week 1 trace shape with document and graph metadata. Langfuse remains the external observability system; LangSmith is not used. Payload capture is disabled by default, so the normal trace contains metadata only.

- OpenEMR document retrieval latency;
- extraction latency;
- extraction confidence;
- schema validation outcome;
- retrieval hits;
- rerank scores;
- supervisor route;
- worker handoffs;
- final compose latency;
- verification result;
- token usage from API usage fields;
- estimated cost;
- eval outcome when running evals.

PHI-safe Langfuse spans:

- `agentforge.supervisor`;
- `agentforge.intake_extractor`;
- `agentforge.evidence_retriever`;
- `agentforge.answer_worker`;
- `agentforge.critic_verifier`.

The UI trace panel exposes the same graph route and worker handoff metadata for demo inspection. Source display is grouped as Patient Chart, Extracted Documents, and Guidelines, with document facts linking back to the OpenEMR document viewer.

Expected bottlenecks are PDF/image extraction, embedding calls, rerank, and final compose/verify. The architecture keeps those bounded by limiting page count, caching guideline embeddings, passing structured extracted facts instead of full document text to the composer, and keeping top-k retrieval small.

The final Week 2 cost and latency report should include actual dev spend, p50/p95 latency by stage, projected production costs, and scale bottlenecks. The goal is not merely cost-per-token math; the report must account for extraction frequency, document size, caching, retries, eval runs, observability, and concurrency.

## Risks And Tradeoffs

The largest risk is treating extracted document facts as chart truth too early. The Week 2 design avoids that by storing source documents in OpenEMR, keeping derived facts in module-owned traceable tables, requiring citations, and surfacing low-confidence extraction as a warning.

Local rerank is a pragmatic dependency choice. It avoids a second paid API key and keeps deployment simpler, but it may be weaker than Cohere on nuanced guideline ranking. The design keeps a reranker boundary so Cohere or another reranker can be added later without changing response contracts.

The supervisor graph is intentionally small. A critic agent, third document type, lab trend widget, and richer query rewriting are useful extensions, but they are not required for the hard Week 2 gate. The core build should prove the narrow flow: two document types, two workers, grounded guideline retrieval, visual citations, and eval-driven CI.

## Final Position

The defended Week 2 architecture is narrow by design. It adds multimodal inputs and multi-agent routing without weakening the Week 1 trust boundary. OpenEMR remains the source of authorization and document ownership. The sidecar remains a bounded AI runtime. The model extracts and composes, but schemas, citations, verifier checks, warnings, and evals decide what is allowed to reach the physician.
