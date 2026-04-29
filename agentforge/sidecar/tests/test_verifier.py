import unittest

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


def request_with_source(value="Pneumonia"):
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
                    id="problem-1",
                    record_type="problem",
                    recorded_at="2026-04-29T08:00:00Z",
                    field_path="lists.title",
                    value=value,
                )
            ],
            adapter_status=[AdapterStatus(adapter="problem_list", status="success")],
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

    def test_treatment_request_is_refused(self):
        request = request_with_source()
        request = request.model_copy(update={"message": "Should I start ceftriaxone?"})
        response, _trace = handle_chat(request, Settings(mode="mock"))
        self.assertEqual(response.verification_status, "refused")

    def test_collector_failure_produces_partial(self):
        request = request_with_source()
        bundle = request.evidence_bundle.model_copy(
            update={"adapter_status": [AdapterStatus(adapter="labs", status="timeout", reason="demo timeout")]}
        )
        request = request.model_copy(update={"evidence_bundle": bundle})
        response, _trace = handle_chat(request, Settings(mode="mock"))
        self.assertEqual(response.verification_status, "partial")
        self.assertTrue(response.warnings)


if __name__ == "__main__":
    unittest.main()
