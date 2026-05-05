# AgentForge Contracts

These contracts define the boundary between the OpenEMR module and the AI sidecar.

OpenEMR is responsible for authentication, authorization, patient context, evidence collection, request signing, and patient-linked audit events. The sidecar receives only the signed request and bounded evidence bundle. It does not receive database credentials, OpenEMR API tokens, callback tools, or authority to fetch more chart data.

## Versions

- Request schema: `agentforge.request.v1`
- Response schema: `agentforge.response.v1`
- Document extraction request schema: `agentforge.document_extract.v1`
- Document extraction response schema: `agentforge.document_extract.response.v1`

## Week 2 Document Boundary

OpenEMR Documents stores the source files. The AgentForge module selects an existing patient document and sends a signed, short-lived extraction request to the same sidecar. The sidecar returns structured extracted facts with source citation metadata. Extracted facts are stored in module-owned AgentForge tables and re-enter later chat requests as `document_fact` evidence sources, not as core OpenEMR clinical truth.

Minimum citation fields:

```json
{
  "source_type": "lab_pdf",
  "source_id": "openemr-document-123",
  "page_or_section": "page 1",
  "field_or_chunk_id": "lab-result-potassium",
  "quote_or_value": "Potassium 5.8 mmol/L",
  "bounding_box": null
}
```

## Response Statuses

- `verified`: every factual clinical claim is source-bound and supported by the evidence bundle.
- `partial`: all displayed claims are source-bound, but relevant evidence for the requested question was unavailable, citation repair was incomplete, or the answer can only be partially supported by the bounded snapshot. Missing unrelated collectors may still appear as warnings without forcing `partial`.
- `refused`: the request asks for a treatment directive, unauthorized data, cross-patient context, or an ungrounded conclusion.
- `failed`: malformed input, sidecar failure, provider failure, or verifier failure prevents a controlled answer.

## State Scope

Conversation state is scoped to:

```text
conversation_id + patient_id + encounter_id + evidence_bundle_id
```

Switching patients or encounters requires a fresh evidence bundle. The sidecar may keep PHI-safe operational metadata, but it must not persist raw chart evidence as conversational memory.
