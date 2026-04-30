import unittest
from contextlib import contextmanager
from unittest.mock import patch

from agentforge_sidecar import observability
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


class _FakeObservation:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class _FakeObservationContext:
    def __init__(self, observation):
        self.observation = observation

    def __enter__(self):
        return self.observation

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeLangfuse:
    def __init__(self):
        self.observations = []

    def start_as_current_observation(self, **kwargs):
        observation = _FakeObservation(kwargs)
        self.observations.append(observation)
        return _FakeObservationContext(observation)


@contextmanager
def _fake_propagate_attributes(**_kwargs):
    yield


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
        self.assertIn("did not find retrieved evidence", verified.answer.lower())
        self.assertIn("give me a chart brief", verified.answer.lower())
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

    def test_real_mode_uses_ai_path_for_allergy_question(self):
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
        ai_response = mock_response(request, "trace-test")
        class _Diag:
            tool_call_count = 1
            selected_source_count = 0
            fallback_reason = "no_supporting_evidence_selected"
            planning_latency_ms = 10
            compose_latency_ms = 0

        with patch("agentforge_sidecar.service.openai_response", return_value=(ai_response, _Diag())) as openai_response:
            response, _trace = handle_chat(request, Settings(mode="real"))
        openai_response.assert_called_once()
        self.assertEqual(response.verification_status, "partial")

    def test_real_mode_uses_ai_path_for_heart_question(self):
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
        ai_response = mock_response(request, "trace-test")

        class _Diag:
            tool_call_count = 2
            selected_source_count = 3
            fallback_reason = ""
            planning_latency_ms = 12
            compose_latency_ms = 23

        with patch("agentforge_sidecar.service.openai_response", return_value=(ai_response, _Diag())) as openai_response:
            response, trace = handle_chat(request, Settings(mode="real"))
        openai_response.assert_called_once()
        self.assertEqual(trace.tool_call_count, 2)
        self.assertEqual(trace.selected_source_count, 3)
        self.assertEqual(trace.planning_latency_ms, 12)
        self.assertEqual(trace.compose_latency_ms, 23)
        self.assertIn("active chart issues", response.answer.lower())

    def test_real_mode_uses_ai_path_for_eye_question(self):
        request = request_with_source(value="Hypertension")
        request = request.model_copy(update={"message": "Does this patient have any eye issues?"})
        ai_response = mock_response(request, "trace-test")

        class _Diag:
            tool_call_count = 1
            selected_source_count = 1
            fallback_reason = ""
            planning_latency_ms = 11
            compose_latency_ms = 21

        with patch("agentforge_sidecar.service.openai_response", return_value=(ai_response, _Diag())) as openai_response:
            _response, _trace = handle_chat(request, Settings(mode="real"))
        openai_response.assert_called_once()

    def test_real_mode_provider_exception_degrades_to_partial(self):
        request = request_with_source(value="Hypertension")
        request = request.model_copy(update={"message": "Any active cardiac issues?"})
        with patch("agentforge_sidecar.service.openai_response", side_effect=RuntimeError("provider boom")):
            response, _trace = handle_chat(request, Settings(mode="real"))
        self.assertEqual(response.verification_status, "partial")
        self.assertTrue(any(warning.code == "sidecar_exception" for warning in response.warnings))
        self.assertIn("active cardiac issues", response.answer.lower())

    def test_partial_after_blocking_uses_physician_natural_answer(self):
        request = request_with_source("Pneumonia")
        response = mock_response(request, "trace-test")
        response.claims[0] = Claim(
            id="claim-supported",
            text="Problem list includes pneumonia",
            claim_type="problem",
            source_ids=["problem-1"],
            support_status="supported",
        )
        response.claims.append(
            Claim(
                id="claim-unsupported",
                text="Patient has diabetes",
                claim_type="problem",
                source_ids=["problem-1"],
                support_status="supported",
            )
        )
        verified = verify_response(request, response)
        self.assertEqual(verified.verification_status, "partial")
        self.assertIn("based on retrieved chart evidence", verified.answer.lower())
        self.assertNotIn("removed unsupported generated claims", verified.answer.lower())

    def test_langfuse_metadata_mode_does_not_capture_phi_payloads(self):
        request = request_with_source("Pneumonia")
        fake_langfuse = _FakeLangfuse()
        settings = Settings(mode="mock", langfuse_enabled=True, langfuse_capture_payloads=False)

        with patch.object(observability, "_load_langfuse", return_value=(fake_langfuse, _fake_propagate_attributes)):
            response, _trace = handle_chat(request, settings)

        self.assertEqual(response.verification_status, "verified")
        self.assertEqual(len(fake_langfuse.observations), 1)
        root = fake_langfuse.observations[0]
        self.assertNotIn("message", root.kwargs["input"])
        self.assertTrue(root.updates)
        self.assertNotIn("answer", root.updates[-1]["output"])

    def test_langfuse_payload_capture_is_explicit(self):
        request = request_with_source("Pneumonia")
        fake_langfuse = _FakeLangfuse()
        settings = Settings(mode="mock", langfuse_enabled=True, langfuse_capture_payloads=True)

        with patch.object(observability, "_load_langfuse", return_value=(fake_langfuse, _fake_propagate_attributes)):
            response, _trace = handle_chat(request, settings)

        root = fake_langfuse.observations[0]
        self.assertEqual(root.kwargs["input"]["message"], request.message)
        self.assertEqual(root.updates[-1]["output"]["answer"], response.answer)


if __name__ == "__main__":
    unittest.main()
