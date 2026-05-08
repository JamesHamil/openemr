import base64
import unittest
from datetime import datetime, timedelta, timezone

from agentforge_sidecar.document_extraction import extract_document
from agentforge_sidecar.schemas import (
    AdapterStatus,
    AgentForgeRequest,
    DocumentExtractionRequest,
    EvidenceSource,
    PatientContext,
    RoundingContextBundle,
    Scope,
)
from agentforge_sidecar.service import handle_chat
from agentforge_sidecar.settings import Settings


def _scope(case_id="graph") -> Scope:
    return Scope(
        user_hash="graph-user",
        patient_hash=f"graph-patient-{case_id}",
        encounter_hash="graph-encounter",
        evidence_bundle_id=f"graph-bundle-{case_id}",
    )


def _chat_request(message: str) -> AgentForgeRequest:
    return AgentForgeRequest(
        schema_version="agentforge.request.v1",
        request_id="graph-chat",
        conversation_id="graph-conversation",
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        purpose="unit-test",
        scope=_scope(),
        message=message,
        evidence_bundle=RoundingContextBundle(
            id="bundle-graph",
            created_at=datetime.now(timezone.utc).isoformat(),
            patient_context=PatientContext(patient_id="1", encounter_id="2"),
            sources=[
                EvidenceSource(
                    id="document-fact-1",
                    record_type="document_fact",
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    field_path="agentforge_extracted_facts.lab_result",
                    value="Potassium; result 5.8; unit mmol/L; abnormal high",
                    metadata={"source_kind": "document_extraction", "document_type": "lab_pdf"},
                )
            ],
            adapter_status=[AdapterStatus(adapter="agentforge_documents", status="success")],
        ),
    )


def _intake_chat_request(message: str) -> AgentForgeRequest:
    return AgentForgeRequest(
        schema_version="agentforge.request.v1",
        request_id="graph-chat-intake",
        conversation_id="graph-conversation",
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        purpose="unit-test",
        scope=_scope("intake"),
        message=message,
        evidence_bundle=RoundingContextBundle(
            id="bundle-graph-intake",
            created_at=datetime.now(timezone.utc).isoformat(),
            patient_context=PatientContext(patient_id="1", encounter_id="2"),
            sources=[
                EvidenceSource(
                    id="document-fact-273",
                    record_type="document_fact",
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    field_path="agentforge_extracted_facts.pharmacy",
                    value="Preferred Pharmacy Name; MediMart",
                    metadata={"source_kind": "document_extraction", "document_type": "intake_form"},
                ),
                EvidenceSource(
                    id="document-fact-271",
                    record_type="document_fact",
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    field_path="agentforge_extracted_facts.social_history",
                    value="Alcohol; Occasionally",
                    metadata={"source_kind": "document_extraction", "document_type": "intake_form"},
                ),
            ],
            adapter_status=[
                AdapterStatus(adapter="agentforge_documents", status="success"),
                AdapterStatus(adapter="allergies", status="unavailable", reason="No active allergy records found."),
            ],
        ),
    )


class SupervisorGraphTest(unittest.TestCase):
    def test_chat_graph_records_supervisor_worker_and_guideline_metadata(self):
        response, trace = handle_chat(_chat_request("What should I review for this abnormal potassium?"), Settings(mode="mock"))

        self.assertEqual(trace.supervisor_route, "retrieve_then_answer")
        self.assertEqual(trace.graph_nodes, ["supervisor", "evidence_retriever", "answer_worker", "critic_verifier"])
        self.assertIn("evidence-retriever", [handoff.worker for handoff in trace.worker_handoffs])
        self.assertGreaterEqual(trace.guideline_retrieval_hits or 0, 1)
        self.assertEqual(response.debug_trace["supervisor_route"], "retrieve_then_answer")

    def test_document_only_chat_skips_guideline_retrieval(self):
        response, trace = handle_chat(_intake_chat_request("I need to know about this patient's intake form"), Settings(mode="mock"))

        self.assertEqual(trace.supervisor_route, "answer_document_facts")
        self.assertEqual(trace.graph_nodes, ["supervisor", "answer_worker", "critic_verifier"])
        self.assertNotIn("evidence-retriever", [handoff.worker for handoff in trace.worker_handoffs])
        self.assertEqual(trace.guideline_retrieval_hits, 0)
        self.assertEqual(response.debug_trace["guideline_retrieval"]["hits"], 0)

    def test_treatment_directive_stops_at_supervisor(self):
        response, trace = handle_chat(_chat_request("Should I start potassium treatment?"), Settings(mode="mock"))

        self.assertEqual(response.verification_status, "refused")
        self.assertEqual(trace.supervisor_route, "refuse_treatment_directive")
        self.assertEqual(trace.graph_nodes, ["supervisor"])

    def test_document_graph_records_intake_extractor_handoff(self):
        request = DocumentExtractionRequest(
            schema_version="agentforge.document_extract.v1",
            request_id="graph-doc",
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            document_type="intake_form",
            source_id="openemr-document-graph",
            filename="intake.txt",
            mime_type="text/plain",
            content_base64=base64.b64encode(b"Chief concern: cough; Medications: metformin").decode("ascii"),
            text_hint="Chief concern: cough; Medications: metformin",
            scope=_scope("doc"),
        )

        response, trace = extract_document(request, Settings(mode="mock"))

        self.assertEqual(response.extraction_status, "success")
        self.assertEqual(trace["supervisor_route"], "extract_document")
        self.assertEqual(trace["graph_nodes"], ["supervisor", "intake_extractor"])
        self.assertEqual(response.worker_handoffs[0].worker, "intake-extractor")


if __name__ == "__main__":
    unittest.main()
