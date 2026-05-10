import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agentforge_sidecar.clinical_planner import plan_evidence
from agentforge_sidecar.openai_provider import (
    ModelAgentForgeResponse,
    ModelResponseSource,
    ModelVerificationResult,
    _fallback_answer_for_plan,
    _fallback_source_ids_for_plan,
    _limit_response,
    _model_verify_and_repair,
    _plan_needs_lab_augmentation,
    _RESPONSE_CACHE,
    _schema_lab_source_ids_for_plan,
    _selected_source_limit,
    _selected_sources,
    openai_response,
)
from agentforge_sidecar.schemas import (
    AdapterStatus,
    AgentForgeRequest,
    AgentForgeResponse,
    Claim,
    EvidenceSource,
    PatientContext,
    ResponseSource,
    RoundingContextBundle,
    Scope,
    ToolPhaseResult,
)
from agentforge_sidecar.settings import Settings
from agentforge_sidecar.tool_agent import ToolPhaseDiagnostics


class _Parsed:
    def __init__(self, output, input_tokens=0, output_tokens=0):
        self.output_parsed = output
        self.usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


class _FakeResponses:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.parse_calls = []

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        output = self.outputs.pop(0)
        if isinstance(output, tuple):
            parsed, input_tokens, output_tokens = output
            return _Parsed(parsed, input_tokens, output_tokens)
        return _Parsed(output)


class _FakeClient:
    def __init__(self, outputs):
        self.responses = _FakeResponses(outputs)


def _request():
    return AgentForgeRequest(
        schema_version="agentforge.request.v1",
        request_id="req-test",
        conversation_id="conv-test",
        expires_at="2026-04-30T10:00:00Z",
        purpose="patient_rounding_brief",
        scope=Scope(
            user_hash="user",
            patient_hash="patient",
            encounter_hash="encounter",
            evidence_bundle_id="bundle-test",
        ),
        message="What allergies do I need to know before ordering anything?",
        evidence_bundle=RoundingContextBundle(
            id="bundle-test",
            created_at="2026-04-30T09:59:00Z",
            patient_context=PatientContext(patient_id="123", encounter_id="456"),
            sources=[
                EvidenceSource(
                    id="allergy-1",
                    record_type="allergy",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Allergy to eggs",
                )
            ],
            adapter_status=[AdapterStatus(adapter="allergies", status="success")],
        ),
    )


def _response(answer="Documented allergies: eggs. [allergy-1]"):
    return AgentForgeResponse(
        answer=answer,
        sections=[],
        claims=[
            Claim(
                id="claim-1",
                text="Documented allergies include Allergy to eggs.",
                claim_type="allergy",
                source_ids=["allergy-1"],
                support_status="supported",
            ),
            Claim(
                id="claim-2",
                text="Verify reaction severity.",
                claim_type="guidance",
                source_ids=["allergy-1"],
                support_status="supported",
            ),
        ],
        sources=[
            ResponseSource(
                id="allergy-1",
                record_type="allergy",
                display="Allergy source",
                recorded_at="2026-04-30T08:00:00Z",
                field_path="lists.title",
                extracted_value="Allergy to eggs",
            )
        ],
        warnings=[],
        blocked_claims=[],
        verification_status="verified",
        trace_id="trace-test",
    )


class OpenAIProviderTest(unittest.TestCase):
    def test_model_response_schema_does_not_ask_model_for_source_metadata(self):
        from openai.lib._pydantic import to_strict_json_schema

        schema = to_strict_json_schema(ModelAgentForgeResponse)
        source_schema = schema["$defs"]["ModelResponseSource"]

        self.assertNotIn("metadata", source_schema["properties"])
        self.assertNotIn("metadata", source_schema["required"])

    def test_limit_response_allows_claims_to_reuse_source(self):
        request = _request()
        limited = _limit_response(_response(), request.evidence_bundle.sources)

        self.assertEqual([claim.id for claim in limited.claims], ["claim-1", "claim-2"])
        self.assertEqual([source.id for source in limited.sources], ["allergy-1"])

    def test_limit_response_drops_stale_blocked_claim_ids(self):
        request = _request()
        response = _response().model_copy(update={"blocked_claims": ["claim-2", "claim-ghost"]})
        limited = _limit_response(response, request.evidence_bundle.sources)

        self.assertEqual(limited.blocked_claims, ["claim-2"])

    def test_openai_response_skips_model_tool_phase_when_planner_selected_sources(self):
        request = _request()
        composed = ModelAgentForgeResponse(
            answer="Documented allergies include eggs. [allergy-1]",
            claims=[
                Claim(
                    id="claim-1",
                    text="Documented allergies include Allergy to eggs.",
                    claim_type="allergy",
                    source_ids=["allergy-1"],
                    support_status="supported",
                )
            ],
            sources=[
                ModelResponseSource(
                    id="allergy-1",
                    record_type="allergy",
                    display="Allergy source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    extracted_value="Allergy to eggs",
                )
            ],
            verification_status="verified",
            trace_id="trace-test",
        )
        client = _FakeClient(
            [
                (composed, 100, 20),
                (
                    ModelVerificationResult(
                        result="passed",
                        status_recommendation="verified",
                        citation_coverage=1.0,
                    ),
                    80,
                    5,
                ),
            ]
        )
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            with patch("agentforge_sidecar.openai_provider.run_tool_phase") as run_tool_phase:
                response, diagnostics = openai_response(request, "trace-test", Settings(mode="real"))

        run_tool_phase.assert_not_called()
        self.assertEqual(response.verification_status, "verified")
        self.assertEqual(diagnostics.source_selection_mode, "planner")
        self.assertEqual(diagnostics.tool_call_count, 0)
        self.assertEqual(diagnostics.planning_latency_ms, 0)
        self.assertEqual(diagnostics.model_call_count, 1)
        self.assertEqual(diagnostics.verifier_result, "passed")
        self.assertEqual(diagnostics.verify_mode, "deterministic")
        self.assertIn("provider", response.debug_trace)
        self.assertEqual(response.debug_trace["provider"]["source_selection_mode"], "planner")
        self.assertEqual(response.debug_trace["provider"]["latency_strategy"], "deterministic_selection+compose+deterministic_verify")
        self.assertEqual(diagnostics.input_tokens, 100)
        self.assertEqual(diagnostics.output_tokens, 20)

    def test_openai_response_uses_deterministic_selection_for_low_confidence_plan(self):
        request = _request().model_copy(update={"message": "What is the zebulon index?"})
        composed = ModelAgentForgeResponse(
            answer="Retrieved chart evidence shows allergy to eggs. [allergy-1]",
            claims=[
                Claim(
                    id="claim-1",
                    text="Retrieved chart evidence shows Allergy to eggs.",
                    claim_type="allergy",
                    source_ids=["allergy-1"],
                    support_status="supported",
                )
            ],
            sources=[
                ModelResponseSource(
                    id="allergy-1",
                    record_type="allergy",
                    display="Allergy source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    extracted_value="Allergy to eggs",
                )
            ],
            verification_status="verified",
            trace_id="trace-test",
        )
        client = _FakeClient(
            [
                composed,
                ModelVerificationResult(
                    result="passed",
                    status_recommendation="verified",
                    citation_coverage=1.0,
                ),
            ]
        )
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            with patch("agentforge_sidecar.openai_provider.run_tool_phase") as run_tool_phase:
                response, diagnostics = openai_response(request, "trace-test", Settings(mode="real"))

        run_tool_phase.assert_not_called()
        self.assertEqual(response.verification_status, "verified")
        self.assertEqual(diagnostics.source_selection_mode, "deterministic")
        self.assertEqual(diagnostics.tool_call_count, 0)
        self.assertEqual(diagnostics.planning_latency_ms, 0)
        self.assertEqual(diagnostics.model_call_count, 1)

    def test_openai_response_uses_model_tool_phase_when_forced_by_settings(self):
        request = _request().model_copy(update={"message": "What is the zebulon index?"})
        composed = ModelAgentForgeResponse(
            answer="Retrieved chart evidence shows allergy to eggs. [allergy-1]",
            claims=[
                Claim(
                    id="claim-1",
                    text="Retrieved chart evidence shows Allergy to eggs.",
                    claim_type="allergy",
                    source_ids=["allergy-1"],
                    support_status="supported",
                )
            ],
            sources=[
                ModelResponseSource(
                    id="allergy-1",
                    record_type="allergy",
                    display="Allergy source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    extracted_value="Allergy to eggs",
                )
            ],
            verification_status="verified",
            trace_id="trace-test",
        )
        client = _FakeClient(
            [
                composed,
                ModelVerificationResult(
                    result="passed",
                    status_recommendation="verified",
                    citation_coverage=1.0,
                ),
            ]
        )
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            with patch("agentforge_sidecar.openai_provider.run_tool_phase") as run_tool_phase:
                run_tool_phase.return_value = (
                    ToolPhaseResult(selected_source_ids=["allergy-1"], focus="Model selected source."),
                    ToolPhaseDiagnostics(tool_call_count=1, planning_latency_ms=123),
                )
                response, diagnostics = openai_response(
                    request,
                    "trace-test",
                    Settings(mode="real", source_selection_mode="model", verify_mode="model"),
                )

        run_tool_phase.assert_called_once()
        self.assertEqual(response.verification_status, "verified")
        self.assertEqual(diagnostics.source_selection_mode, "model_tool_phase")
        self.assertEqual(diagnostics.verify_mode, "model")
        self.assertEqual(diagnostics.tool_call_count, 1)
        self.assertEqual(diagnostics.planning_latency_ms, 123)

    def test_openai_response_answers_lab_document_facts_without_tool_or_compose(self):
        request = _request().model_copy(update={"message": "How are this patient's CBC labs?"})
        bundle = request.evidence_bundle.model_copy(
            update={
                "sources": [
                    EvidenceSource(
                        id="document-fact-51",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.Manual Absolute Neutrophil Count",
                        value="Manual Absolute Neutrophil Count; 1.14; abnormal Low",
                        metadata={"document_type": "lab_pdf"},
                    ),
                    EvidenceSource(
                        id="document-fact-50",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.Undifferentiated Blasts",
                        value="Undifferentiated Blasts; 5; abnormal High",
                        metadata={"document_type": "lab_pdf"},
                    ),
                    EvidenceSource(
                        id="document-fact-49",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.Promyelocytes",
                        value="Promyelocytes; 3; abnormal High",
                        metadata={"document_type": "lab_pdf"},
                    ),
                    EvidenceSource(
                        id="document-fact-54",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.Interpretation",
                        value="Interpretation; Abnormal lymphocytes are present.",
                        metadata={"document_type": "lab_pdf"},
                    ),
                ],
                "adapter_status": [AdapterStatus(adapter="agentforge_documents", status="success")],
            }
        )
        request = request.model_copy(update={"evidence_bundle": bundle})
        client = _FakeClient([])
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            with patch("agentforge_sidecar.openai_provider.run_tool_phase") as run_tool_phase:
                response, diagnostics = openai_response(request, "trace-test", Settings(mode="real"))

        run_tool_phase.assert_not_called()
        self.assertEqual(len(client.responses.parse_calls), 0)
        self.assertEqual(response.verification_status, "verified")
        self.assertEqual(diagnostics.source_selection_mode, "planner")
        self.assertGreaterEqual(diagnostics.selected_source_count, 4)
        self.assertEqual(diagnostics.model_call_count, 0)
        self.assertEqual(diagnostics.compose_latency_ms, 0)
        self.assertEqual(diagnostics.latency_strategy, "deterministic_selection+deterministic_answer+deterministic_verify")
        self.assertIn("Manual Absolute Neutrophil Count 1.14", response.answer)
        self.assertIn("document-fact-50", {source.id for source in response.sources})
        self.assertEqual(response.debug_trace["provider"]["model_call_count"], 0)

    def test_openai_response_expands_all_intake_phone_numbers_then_answers_directly(self):
        request = _request().model_copy(update={"message": "give me all the phone numbers in the intake form"})
        bundle = request.evidence_bundle.model_copy(
            update={
                "sources": [
                    EvidenceSource(
                        id="document-fact-101",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.demographic",
                        value="Phone; (217) 555-0198",
                        metadata={
                            "document_type": "intake_form",
                            "citation": '{"field_or_chunk_id":"phone","page_or_section":"Patient Information"}',
                        },
                    ),
                    EvidenceSource(
                        id="document-fact-102",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.demographic",
                        value="Emergency Contact Phone; (217) 555-0144",
                        metadata={
                            "document_type": "intake_form",
                            "citation": '{"field_or_chunk_id":"emergency_contact_phone","page_or_section":"Patient Information"}',
                        },
                    ),
                    EvidenceSource(
                        id="document-fact-103",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.pharmacy",
                        value="Phone Number; (217) 555-0160",
                        metadata={
                            "document_type": "intake_form",
                            "citation": '{"field_or_chunk_id":"pharmacy_phone","page_or_section":"Pharmacy Information"}',
                        },
                    ),
                    EvidenceSource(
                        id="document-fact-104",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.email",
                        value="Email; jordan.rivera@example.com",
                        metadata={
                            "document_type": "intake_form",
                            "citation": '{"field_or_chunk_id":"email","page_or_section":"Patient Information"}',
                        },
                    ),
                ],
                "adapter_status": [AdapterStatus(adapter="agentforge_documents", status="success")],
            }
        )
        request = request.model_copy(update={"evidence_bundle": bundle})
        client = _FakeClient([])
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            with patch("agentforge_sidecar.openai_provider.run_tool_phase") as run_tool_phase:
                response, diagnostics = openai_response(request, "trace-test", Settings(mode="real"))

        run_tool_phase.assert_not_called()
        self.assertEqual(len(client.responses.parse_calls), 0)
        self.assertEqual(response.verification_status, "verified")
        self.assertIn("schema_evidence_expansion", diagnostics.source_selection_mode)
        self.assertTrue(diagnostics.source_selection_mode.startswith("planner"))
        self.assertEqual(diagnostics.schema_evidence_expansion["groups"], ["phone_numbers"])
        self.assertEqual(diagnostics.planning_latency_ms, 0)
        self.assertEqual(diagnostics.model_call_count, 0)
        self.assertEqual(diagnostics.selected_source_count, 3)
        self.assertEqual(len(response.claims), 3)
        self.assertEqual(
            [source.id for source in response.sources],
            ["document-fact-101", "document-fact-102", "document-fact-103"],
        )
        self.assertEqual(response.sources[-1].extracted_value, "Pharmacy phone; (217) 555-0160")
        self.assertEqual(response.debug_trace["provider"]["model_call_count"], 0)
        self.assertEqual(
            response.debug_trace["provider"]["latency_strategy"],
            "deterministic_selection+deterministic_answer+deterministic_verify",
        )

    def test_openai_response_answers_emergency_contact_lookup_directly(self):
        request = _request().model_copy(
            update={"message": "what is this patient's emergency contact and their phone number?"}
        )
        bundle = request.evidence_bundle.model_copy(
            update={
                "sources": [
                    EvidenceSource(
                        id="document-fact-332",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.PatientPhone",
                        value="Patient Phone; (217) 555-0198",
                        metadata={"document_type": "intake_form"},
                    ),
                    EvidenceSource(
                        id="document-fact-334",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.EmergencyContactName",
                        value="Emergency Contact Name; Alex Rivera",
                        metadata={"document_type": "intake_form"},
                    ),
                    EvidenceSource(
                        id="document-fact-335",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.EmergencyContactPhone",
                        value="Emergency Contact Phone; (217) 555-0144",
                        metadata={"document_type": "intake_form"},
                    ),
                    EvidenceSource(
                        id="document-fact-349",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.PharmacyPhone",
                        value="Pharmacy Phone; (217) 555-0160",
                        metadata={"document_type": "intake_form"},
                    ),
                ],
                "adapter_status": [AdapterStatus(adapter="agentforge_documents", status="success")],
            }
        )
        request = request.model_copy(update={"evidence_bundle": bundle})
        client = _FakeClient([])
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            with patch("agentforge_sidecar.openai_provider.run_tool_phase") as run_tool_phase:
                response, diagnostics = openai_response(request, "trace-test", Settings(mode="real"))

        run_tool_phase.assert_not_called()
        self.assertEqual(len(client.responses.parse_calls), 0)
        self.assertEqual(diagnostics.schema_evidence_expansion["groups"], ["intake_contact"])
        self.assertEqual(diagnostics.model_call_count, 0)
        self.assertEqual([source.id for source in response.sources], ["document-fact-334", "document-fact-335"])
        self.assertEqual(response.answer, "Emergency contact is Alex Rivera; phone (217) 555-0144.")
        self.assertFalse(response.warnings)

    def test_openai_response_answers_medication_list_document_facts_directly(self):
        request = _request().model_copy(update={"message": "What is in the uploaded medication list?"})
        bundle = request.evidence_bundle.model_copy(
            update={
                "sources": [
                    EvidenceSource(
                        id="document-fact-med-1",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.medication",
                        value="Metformin; Metformin 500 mg by mouth twice daily",
                        metadata={"document_type": "medication_list"},
                    ),
                    EvidenceSource(
                        id="document-fact-med-2",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:59Z",
                        field_path="agentforge_extracted_facts.medication",
                        value="Lisinopril; Lisinopril 10 mg daily",
                        metadata={"document_type": "medication_list"},
                    ),
                    EvidenceSource(
                        id="document-fact-intake",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:26:00Z",
                        field_path="agentforge_extracted_facts.pharmacy",
                        value="Preferred Pharmacy Name; MediMart",
                        metadata={"document_type": "intake_form"},
                    ),
                ],
                "adapter_status": [AdapterStatus(adapter="agentforge_documents", status="success")],
            }
        )
        request = request.model_copy(update={"evidence_bundle": bundle})
        client = _FakeClient([])
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            with patch("agentforge_sidecar.openai_provider.run_tool_phase") as run_tool_phase:
                response, diagnostics = openai_response(request, "trace-test", Settings(mode="real"))

        run_tool_phase.assert_not_called()
        self.assertEqual(len(client.responses.parse_calls), 0)
        self.assertEqual(response.verification_status, "verified")
        self.assertEqual(diagnostics.model_call_count, 0)
        self.assertEqual(diagnostics.source_selection_mode, "planner")
        self.assertEqual([source.id for source in response.sources], ["document-fact-med-2", "document-fact-med-1"])
        self.assertIn("Lisinopril: Lisinopril 10 mg daily", response.answer)
        self.assertIn("Metformin: Metformin 500 mg by mouth twice daily", response.answer)

    def test_med_reconciliation_prefers_chart_prescriptions_after_writeback(self):
        request = _request().model_copy(update={"message": "What medications is this patient on?"})
        document_sources = [
            EvidenceSource(
                id=f"document-fact-med-{index}",
                record_type="document_fact",
                recorded_at=f"2026-05-05T01:25:{index:02d}Z",
                field_path="agentforge_extracted_facts.medication",
                value=f"Medication {index}; {index} mg; 1 daily",
                metadata={"document_type": "medication_list"},
            )
            for index in range(1, 17)
        ]
        chart_sources = [
            EvidenceSource(
                id=f"medication-rx-{index}",
                record_type="medication",
                recorded_at=f"2026-05-05T01:20:{index:02d}Z",
                field_path="prescriptions.drug",
                value=f"Chart Medication {index}",
            )
            for index in range(1, 4)
        ]
        request = request.model_copy(
            update={
                "evidence_bundle": request.evidence_bundle.model_copy(
                    update={
                        "sources": [*chart_sources, *document_sources],
                        "adapter_status": [
                            AdapterStatus(adapter="agentforge_documents", status="success"),
                            AdapterStatus(adapter="medications", status="success"),
                        ],
                    }
                )
            }
        )

        plan = plan_evidence(request)
        selected = _selected_sources(request, list(plan.selected_source_ids), _selected_source_limit(plan))

        self.assertIsNone(_selected_source_limit(plan))
        self.assertEqual(len(selected), 3)
        self.assertFalse(any(source.id in {item.id for item in selected} for source in document_sources))
        self.assertTrue(all(source.id in {item.id for item in selected} for source in chart_sources))

    def test_med_reconciliation_returns_all_selected_current_medications(self):
        request = _request().model_copy(update={"message": "What medications is this patient on?"})
        medication_list_sources = [
            EvidenceSource(
                id=f"medication-list-{index}",
                record_type="medication",
                recorded_at=f"2026-05-05T01:{index:02d}:00Z",
                field_path="lists.title",
                value=f"Medication {index}; instructions frequency: 1 daily",
                metadata={"status": "current", "source_table": "lists", "issue_type": "medication"},
            )
            for index in range(1, 17)
        ]
        prescription_sources = [
            EvidenceSource(
                id=f"medication-rx-{index}",
                record_type="medication",
                recorded_at=f"2026-05-05T00:{index:02d}:00Z",
                field_path="prescriptions.drug",
                value=f"Prescription {index}",
                metadata={"status": "current", "source_table": "prescriptions"},
            )
            for index in range(1, 4)
        ]
        request = request.model_copy(
            update={
                "evidence_bundle": request.evidence_bundle.model_copy(
                    update={
                        "sources": [*medication_list_sources, *prescription_sources],
                        "adapter_status": [AdapterStatus(adapter="medications", status="success")],
                    }
                )
            }
        )
        client = _FakeClient([])
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            with patch("agentforge_sidecar.openai_provider.run_tool_phase") as run_tool_phase:
                response, diagnostics = openai_response(request, "trace-test", Settings(mode="real"))

        run_tool_phase.assert_not_called()
        self.assertEqual(len(client.responses.parse_calls), 0)
        self.assertEqual(response.verification_status, "verified")
        self.assertEqual(diagnostics.model_call_count, 0)
        self.assertEqual(diagnostics.selected_source_count, 19)
        self.assertEqual(len(response.claims), 19)
        self.assertEqual(len(response.sources), 19)
        self.assertIn("Medication 16", response.answer)
        self.assertIn("Prescription 3", response.answer)

    def test_openai_response_intake_summary_skips_tool_phase_and_keeps_compose_payload_narrow(self):
        request = _request().model_copy(update={"message": "I need to know about this patient's intake form"})
        bundle = request.evidence_bundle.model_copy(
            update={
                "sources": [
                    EvidenceSource(
                        id="patient-name-1",
                        record_type="demographic",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="patient_data.fname_lname",
                        value="Bob Bobsy",
                    ),
                    EvidenceSource(
                        id="document-fact-273",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.pharmacy",
                        value="Preferred Pharmacy Name; MediMart",
                        metadata={"document_type": "intake_form"},
                    ),
                    EvidenceSource(
                        id="document-fact-271",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.social_history",
                        value="Alcohol; Occasionally",
                        metadata={"document_type": "intake_form"},
                    ),
                    EvidenceSource(
                        id="guideline-red-flags-1",
                        record_type="guideline",
                        recorded_at="2026-01-01T00:00:00Z",
                        field_path="guidelines.red_flags",
                        value="Review red flags.",
                    ),
                ],
                "adapter_status": [
                    AdapterStatus(adapter="agentforge_documents", status="success"),
                    AdapterStatus(adapter="allergies", status="unavailable", reason="No active allergy records found."),
                ],
            }
        )
        request = request.model_copy(update={"evidence_bundle": bundle})
        composed = ModelAgentForgeResponse(
            answer="The intake form lists MediMart and occasional alcohol use. [document-fact-273]",
            claims=[
                Claim(
                    id="claim-1",
                    text="Preferred pharmacy is MediMart.",
                    claim_type="document_fact",
                    source_ids=["document-fact-273"],
                    support_status="supported",
                )
            ],
            sources=[
                ModelResponseSource(
                    id="document-fact-273",
                    record_type="document_fact",
                    display="Document Fact source",
                    recorded_at="2026-05-05T01:25:58Z",
                    field_path="agentforge_extracted_facts.pharmacy",
                    extracted_value="Preferred Pharmacy Name; MediMart",
                )
            ],
            verification_status="verified",
            trace_id="trace-test",
        )
        client = _FakeClient(
            [
                composed,
                ModelVerificationResult(
                    result="passed",
                    status_recommendation="verified",
                    citation_coverage=1.0,
                ),
            ]
        )
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            with patch("agentforge_sidecar.openai_provider.run_tool_phase") as run_tool_phase:
                response, diagnostics = openai_response(request, "trace-test", Settings(mode="real"))

        run_tool_phase.assert_not_called()
        self.assertEqual(diagnostics.source_selection_mode, "planner")
        self.assertEqual(diagnostics.model_call_count, 1)
        compose_payload = _parse_compose_payload(client.responses.parse_calls[0])
        self.assertEqual(compose_payload["adapter_status"][0]["adapter"], "agentforge_documents")
        self.assertEqual(len(compose_payload["adapter_status"]), 1)
        self.assertIn("document-fact-273", compose_payload["selected_source_ids"])
        self.assertIn("document-fact-271", compose_payload["selected_source_ids"])
        self.assertNotIn("patient-name-1", compose_payload["selected_source_ids"])
        self.assertNotIn("guideline-red-flags-1", compose_payload["selected_source_ids"])
        self.assertEqual(response.debug_trace["provider"]["answer_family"], "document_facts")

    def test_schema_completion_guard_marks_omitted_phone_facts_partial(self):
        request = _request().model_copy(update={"message": "give me all the phone numbers in the intake form"})
        bundle = request.evidence_bundle.model_copy(
            update={
                "sources": [
                    EvidenceSource(
                        id="document-fact-101",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.demographic",
                        value="Phone; (217) 555-0198",
                        metadata={
                            "document_type": "intake_form",
                            "citation": '{"field_or_chunk_id":"phone","page_or_section":"Patient Information"}',
                        },
                    ),
                    EvidenceSource(
                        id="document-fact-102",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.demographic",
                        value="Emergency Contact Phone; (217) 555-0144",
                        metadata={
                            "document_type": "intake_form",
                            "citation": '{"field_or_chunk_id":"emergency_contact_phone","page_or_section":"Patient Information"}',
                        },
                    ),
                    EvidenceSource(
                        id="document-fact-103",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.pharmacy",
                        value="Phone Number; (217) 555-0160",
                        metadata={
                            "document_type": "intake_form",
                            "citation": '{"field_or_chunk_id":"pharmacy_phone","page_or_section":"Pharmacy Information"}',
                        },
                    ),
                ],
                "adapter_status": [AdapterStatus(adapter="agentforge_documents", status="success")],
            }
        )
        request = request.model_copy(update={"evidence_bundle": bundle})
        composed = ModelAgentForgeResponse(
            answer="The intake form lists the pharmacy phone. [document-fact-103]",
            claims=[
                Claim(
                    id="claim-1",
                    text="Pharmacy phone is (217) 555-0160.",
                    claim_type="document_fact",
                    source_ids=["document-fact-103"],
                    support_status="supported",
                )
            ],
            sources=[
                ModelResponseSource(
                    id="document-fact-103",
                    record_type="document_fact",
                    display="Document Fact source",
                    recorded_at="2026-05-05T01:25:58Z",
                    field_path="agentforge_extracted_facts.pharmacy",
                    extracted_value="Pharmacy Phone; (217) 555-0160",
                )
            ],
            verification_status="verified",
            trace_id="trace-test",
        )
        client = _FakeClient(
            [
                composed,
                ModelVerificationResult(
                    result="passed",
                    status_recommendation="verified",
                    citation_coverage=1.0,
                ),
            ]
        )
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            with patch("agentforge_sidecar.openai_provider.run_tool_phase") as run_tool_phase:
                with patch("agentforge_sidecar.openai_provider._deterministic_document_fact_response", return_value=None):
                    run_tool_phase.return_value = (
                        ToolPhaseResult(selected_source_ids=["document-fact-103"], focus="Model selected one phone fact."),
                        ToolPhaseDiagnostics(tool_call_count=1, planning_latency_ms=123),
                    )
                    response, diagnostics = openai_response(request, "trace-test", Settings(mode="real"))

        self.assertEqual(response.verification_status, "partial")
        self.assertEqual(response.warnings[-1].code, "schema_evidence_omitted")
        self.assertEqual(
            response.debug_trace["schema_evidence_completion"]["missing_source_ids"],
            ["document-fact-101", "document-fact-102"],
        )
        self.assertEqual(diagnostics.selected_source_count, 3)

    def test_model_verifier_repair_loop_returns_repaired_response(self):
        request = _request()
        repaired = _response("Documented allergies: eggs; verify reaction severity. [allergy-1]")
        client = _FakeClient(
            [
                ModelVerificationResult(
                    result="repairable",
                    issues=["Needs tighter citation."],
                    status_recommendation="partial",
                    citation_coverage=0.5,
                ),
                (repaired, 55, 11),
            ]
        )

        response, metadata = _model_verify_and_repair(
            client=client,
            model="gpt-test",
            settings=Settings(mode="real", verify_mode="model"),
            request=request,
            response=_response("Eggs are documented; verify severity."),
            selected_sources=request.evidence_bundle.sources,
            evidence_plan=plan_evidence(request),
            trace_id="trace-test",
        )

        self.assertEqual(response.answer, repaired.answer)
        self.assertEqual(metadata.repair_count, 1)
        self.assertEqual(metadata.status_reason, "model_verifier_repaired")
        self.assertEqual(metadata.input_tokens, 55)
        self.assertEqual(metadata.output_tokens, 11)

    def test_response_cache_reuses_fast_path_without_model_call(self):
        _RESPONSE_CACHE.clear()
        request = _request()
        composed = ModelAgentForgeResponse(
            answer="Documented allergies include eggs. [allergy-1]",
            claims=[
                Claim(
                    id="claim-1",
                    text="Documented allergies include Allergy to eggs.",
                    claim_type="allergy",
                    source_ids=["allergy-1"],
                    support_status="supported",
                )
            ],
            sources=[
                ModelResponseSource(
                    id="allergy-1",
                    record_type="allergy",
                    display="Allergy source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    extracted_value="Allergy to eggs",
                )
            ],
            verification_status="verified",
            trace_id="trace-one",
        )
        client = _FakeClient([(composed, 100, 20)])
        settings = Settings(mode="real", response_cache_enabled=True)
        openai_module = SimpleNamespace(OpenAI=lambda: client)

        with patch.dict("sys.modules", {"openai": openai_module}):
            first_response, first_diagnostics = openai_response(request, "trace-one", settings)
        second_response, second_diagnostics = openai_response(request, "trace-two", settings)

        self.assertFalse(first_diagnostics.cache_hit)
        self.assertTrue(second_diagnostics.cache_hit)
        self.assertEqual(second_diagnostics.model_call_count, 0)
        self.assertEqual(second_response.trace_id, "trace-two")
        self.assertEqual(second_response.answer, first_response.answer)

    def test_missing_data_empty_selection_fallback_names_unavailable_adapters(self):
        request = _request().model_copy(update={"message": "What is missing that I need before making clinical decisions?"})
        bundle = request.evidence_bundle.model_copy(
            update={
                "sources": [],
                "adapter_status": [
                    AdapterStatus(adapter="labs", status="unavailable", reason="No labs found."),
                    AdapterStatus(adapter="recent_notes", status="unavailable", reason="No notes found."),
                ],
            }
        )
        request = request.model_copy(update={"evidence_bundle": bundle})

        answer = _fallback_answer_for_plan(request, plan_evidence(request))

        self.assertIn("labs", answer)
        self.assertIn("recent notes", answer)
        self.assertIn("confirm in chart", answer)

    def test_lab_plan_augments_thin_model_selection_with_document_facts(self):
        request = _request().model_copy(update={"message": "How are this patient's labs?"})
        bundle = request.evidence_bundle.model_copy(
            update={
                "sources": [
                    EvidenceSource(
                        id="document-fact-54",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.Interpretation",
                        value="Interpretation; Abnormal lymphocytes are present; consider chronic lymphocytic leukemia.",
                        metadata={"document_type": "lab_pdf"},
                    ),
                    EvidenceSource(
                        id="document-fact-51",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.Manual Absolute Neutrophil Count",
                        value="Manual Absolute Neutrophil Count; 1.14; abnormal Low",
                        metadata={"document_type": "lab_pdf"},
                    ),
                    EvidenceSource(
                        id="document-fact-42",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.Platelet Count",
                        value="Platelet Count; 52; abnormal Low",
                        metadata={"document_type": "lab_pdf"},
                    ),
                    EvidenceSource(
                        id="document-fact-41",
                        record_type="document_fact",
                        recorded_at="2026-05-05T01:25:58Z",
                        field_path="agentforge_extracted_facts.Leukocytes",
                        value="Leukocytes; 10.4; abnormal High",
                        metadata={"document_type": "lab_pdf"},
                    ),
                ],
                "adapter_status": [AdapterStatus(adapter="agentforge_documents", status="success")],
            }
        )
        request = request.model_copy(update={"evidence_bundle": bundle})
        plan = plan_evidence(request)

        self.assertTrue(_plan_needs_lab_augmentation(plan, [bundle.sources[0]]))
        self.assertGreaterEqual(len(_fallback_source_ids_for_plan(request, plan)), 4)
        self.assertGreaterEqual(len(_schema_lab_source_ids_for_plan(request, plan, [bundle.sources[0]])), 4)


def _parse_compose_payload(parse_call: dict) -> dict:
    user_message = parse_call["input"][1]["content"]
    return json.loads(user_message.split(":\n", 1)[1])


def _parse_verify_payload(parse_call: dict) -> dict:
    user_message = parse_call["input"][1]["content"]
    return json.loads(user_message.split(":\n", 1)[1])


if __name__ == "__main__":
    unittest.main()
