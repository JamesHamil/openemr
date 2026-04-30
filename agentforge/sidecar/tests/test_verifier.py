import unittest
from unittest.mock import patch

from agentforge_sidecar.mock_provider import mock_response
from agentforge_sidecar.schemas import (
    AdapterStatus,
    AgentForgeRequest,
    Claim,
    EvidenceSource,
    PatientContext,
    RoundingContextBundle,
    Scope,
)
from agentforge_sidecar.service import handle_chat
from agentforge_sidecar.settings import Settings
from agentforge_sidecar.verifier import verify_response


def request_with_source(value="Pneumonia", record_type="problem", source_id="problem-1", field_path="lists.title"):
    return AgentForgeRequest(
        schema_version="agentforge.request.v1",
        request_id="req-test",
        conversation_id="conv-test",
        expires_at="2026-04-29T12:00:00Z",
        purpose="patient_rounding_brief",
        scope=Scope(
            user_hash="user",
            patient_hash="patient",
            encounter_hash="encounter",
            evidence_bundle_id="bundle-test",
        ),
        message="Give me a chart brief for rounds.",
        evidence_bundle=RoundingContextBundle(
            id="bundle-test",
            created_at="2026-04-29T11:59:00Z",
            patient_context=PatientContext(patient_id="123", encounter_id="456"),
            sources=[
                EvidenceSource(
                    id=source_id,
                    record_type=record_type,
                    recorded_at="2026-04-29T08:00:00Z",
                    field_path=field_path,
                    value=value,
                )
            ],
            adapter_status=[AdapterStatus(adapter=f"{record_type}s", status="success")],
        ),
    )


def request_with_sources(message, sources, statuses):
    return AgentForgeRequest(
        schema_version="agentforge.request.v1",
        request_id="req-test",
        conversation_id="conv-test",
        expires_at="2026-04-29T12:00:00Z",
        purpose="patient_rounding_brief",
        scope=Scope(
            user_hash="user",
            patient_hash="patient",
            encounter_hash="encounter",
            evidence_bundle_id="bundle-test",
        ),
        message=message,
        evidence_bundle=RoundingContextBundle(
            id="bundle-test",
            created_at="2026-04-29T11:59:00Z",
            patient_context=PatientContext(patient_id="123", encounter_id="456"),
            sources=sources,
            adapter_status=statuses,
        ),
    )


class VerifierTest(unittest.TestCase):
    def test_mock_response_is_verified(self):
        request = request_with_source()
        response, _trace = handle_chat(request, Settings(mode="mock"))
        self.assertEqual(response.verification_status, "verified")
        self.assertEqual(response.blocked_claims, [])

    def test_unsupported_claim_is_blocked(self):
        request = request_with_source("Pneumonia")
        response = mock_response(request, "trace-test")
        response.claims[0] = Claim(
            id="claim-bad",
            text="The retrieved problem source includes diabetes.",
            claim_type="problem",
            source_ids=["problem-1"],
            support_status="supported",
        )
        verified = verify_response(request, response)
        self.assertEqual(verified.verification_status, "partial")
        self.assertIn("claim-bad", verified.blocked_claims)
        self.assertNotIn("diabetes", verified.answer.lower())
        self.assertEqual(verified.claims, [])

    def test_treatment_request_is_refused(self):
        request = request_with_source()
        request = request.model_copy(update={"message": "Should I start ceftriaxone?"})
        response, _trace = handle_chat(request, Settings(mode="mock"))
        self.assertEqual(response.verification_status, "refused")

    def test_treatment_request_is_refused_before_real_model_call(self):
        request = request_with_source()
        request = request.model_copy(update={"message": "Please start ceftriaxone now."})
        with patch("agentforge_sidecar.service.openai_response") as openai_response:
            response, _trace = handle_chat(request, Settings(mode="real"))
        self.assertEqual(response.verification_status, "refused")
        openai_response.assert_not_called()

    def test_collector_failure_produces_partial(self):
        request = request_with_source()
        bundle = request.evidence_bundle.model_copy(
            update={"adapter_status": [AdapterStatus(adapter="labs", status="timeout", reason="demo timeout")]}
        )
        request = request.model_copy(update={"evidence_bundle": bundle})
        response, _trace = handle_chat(request, Settings(mode="mock"))
        self.assertEqual(response.verification_status, "partial")
        self.assertTrue(response.warnings)

    def test_lab_claim_can_be_verified(self):
        request = request_with_source(
            value="Potassium; result 5.8; units mmol/L; abnormal high",
            record_type="lab",
            source_id="lab-1",
            field_path="procedure_result.result",
        )
        response, _trace = handle_chat(request, Settings(mode="mock"))
        self.assertEqual(response.verification_status, "verified")
        self.assertEqual(response.claims[0].claim_type, "lab")

    def test_direct_allergy_question_bypasses_real_model(self):
        request = request_with_sources(
            "Does this guy have allergies?",
            [
                EvidenceSource(
                    id="problem-1",
                    record_type="problem",
                    recorded_at="2026-04-29T08:00:00Z",
                    field_path="lists.title",
                    value="Hypertension",
                )
            ],
            [
                AdapterStatus(adapter="problem_list", status="success"),
                AdapterStatus(adapter="allergies", status="unavailable", reason="No active records found in retrieved lists."),
            ],
        )
        with patch("agentforge_sidecar.service.openai_response") as openai_response:
            response, _trace = handle_chat(request, Settings(mode="real"))
        self.assertEqual(response.verification_status, "partial")
        self.assertIn("allergy", response.answer.lower())
        self.assertNotIn("hypertension", response.answer.lower())
        openai_response.assert_not_called()

    def test_direct_heart_question_filters_unrelated_chart_facts(self):
        request = request_with_sources(
            "Does this patient have any heart issues?",
            [
                EvidenceSource(
                    id="problem-1",
                    record_type="problem",
                    recorded_at="2026-04-29T08:00:00Z",
                    field_path="lists.title",
                    value="Hypertension",
                ),
                EvidenceSource(
                    id="lab-1",
                    record_type="lab",
                    recorded_at="2026-04-29T08:00:00Z",
                    field_path="procedure_result.result",
                    value="Creatinine; result 1.419; units mg/dL",
                ),
                EvidenceSource(
                    id="medication-1",
                    record_type="medication",
                    recorded_at="2026-04-29T08:00:00Z",
                    field_path="prescriptions.drug",
                    value="Hydrochlorothiazide 12.5 MG",
                ),
            ],
            [
                AdapterStatus(adapter="problem_list", status="success"),
                AdapterStatus(adapter="labs", status="success"),
                AdapterStatus(adapter="medications", status="success"),
            ],
        )
        with patch("agentforge_sidecar.service.openai_response") as openai_response:
            response, _trace = handle_chat(request, Settings(mode="real"))
        self.assertEqual(response.verification_status, "verified")
        self.assertIn("hypertension", response.answer.lower())
        self.assertNotIn("creatinine", response.answer.lower())
        self.assertNotIn("hydrochlorothiazide", response.answer.lower())
        self.assertEqual([source.record_type for source in response.sources], ["problem"])
        openai_response.assert_not_called()


if __name__ == "__main__":
    unittest.main()
