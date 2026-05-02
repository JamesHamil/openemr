import unittest
from contextlib import contextmanager
from unittest.mock import patch

from agentforge_sidecar import observability
from agentforge_sidecar.mock_provider import mock_response
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

    def test_unrelated_missing_collector_does_not_force_partial(self):
        request = request_with_sources(
            "Any active cardiac issues?",
            [
                EvidenceSource(
                    id="problem-1",
                    record_type="problem",
                    recorded_at="2026-04-29T08:00:00Z",
                    field_path="lists.title",
                    value="Hyperlipidemia",
                )
            ],
            [
                AdapterStatus(adapter="problem_list", status="success"),
                AdapterStatus(adapter="recent_notes", status="unavailable", reason="No notes found."),
            ],
        )
        response = mock_response(request, "trace-test")
        verified = verify_response(request, response)

        self.assertEqual(verified.verification_status, "verified")
        self.assertTrue(any(warning.code == "collector_unavailable" for warning in verified.warnings))

    def test_negative_allergy_source_verifies_without_partial(self):
        request = request_with_sources(
            "What allergies do I need to know before ordering anything?",
            [
                EvidenceSource(
                    id="allergy-none-123",
                    record_type="allergy",
                    recorded_at="2026-04-29T08:00:00Z",
                    field_path="lists.type=allergy",
                    value="No active allergies reported in retrieved OpenEMR allergy lists.",
                    metadata={"status": "absent"},
                )
            ],
            [AdapterStatus(adapter="allergies", status="success")],
        )
        response, _trace = handle_chat(request, Settings(mode="mock"))

        self.assertEqual(response.verification_status, "verified")
        self.assertIn("No active allergies", response.answer)
        self.assertEqual(response.sources[0].id, "allergy-none-123")

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

    def test_supported_lab_partial_is_normalized_to_verified(self):
        request = request_with_sources(
            "Give me a chart brief for rounds.",
            [
                EvidenceSource(
                    id="problem-1",
                    record_type="problem",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Pneumonia",
                ),
                EvidenceSource(
                    id="lab-1",
                    record_type="lab",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="procedure_result.result",
                    value="Potassium; result 5.8; units mmol/L; range 3.5-5.1; abnormal high",
                ),
            ],
            [
                AdapterStatus(adapter="problem_list", status="success"),
                AdapterStatus(adapter="labs", status="success"),
            ],
        )
        response = AgentForgeResponse(
            answer="Patient has pneumonia and potassium is elevated at 5.8 mmol/L.",
            sections=[],
            claims=[
                Claim(
                    id="claim-problem",
                    text="Problem list includes Pneumonia.",
                    claim_type="problem",
                    source_ids=["problem-1"],
                    support_status="supported",
                ),
                Claim(
                    id="claim-lab",
                    text="Potassium is elevated at 5.8 mmol/L.",
                    claim_type="lab",
                    source_ids=["lab-1"],
                    support_status="supported",
                ),
            ],
            sources=[
                ResponseSource(
                    id="problem-1",
                    record_type="problem",
                    display="Problem source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    extracted_value="Pneumonia",
                ),
                ResponseSource(
                    id="lab-1",
                    record_type="lab",
                    display="Lab source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="procedure_result.result",
                    extracted_value="Potassium; result 5.8; units mmol/L; range 3.5-5.1; abnormal high",
                ),
            ],
            warnings=[],
            blocked_claims=[],
            verification_status="partial",
            trace_id="trace-test",
        )

        verified = verify_response(request, response)

        self.assertEqual(verified.verification_status, "verified")
        self.assertEqual(verified.blocked_claims, [])

    def test_conflicting_note_change_claim_is_preserved(self):
        request = request_with_sources(
            "What changed since last review?",
            [
                EvidenceSource(
                    id="note-1",
                    record_type="note",
                    recorded_at="2026-04-30T07:00:00Z",
                    field_path="notes.body",
                    value="Shortness of breath improved overnight",
                ),
                EvidenceSource(
                    id="note-2",
                    record_type="note",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="notes.body",
                    value="Shortness of breath worsened this morning",
                ),
            ],
            [AdapterStatus(adapter="recent_notes", status="success")],
        )
        response = AgentForgeResponse(
            answer="Recent notes conflict: shortness of breath improved overnight, then worsened this morning.",
            sections=[],
            claims=[
                Claim(
                    id="claim-change",
                    text="Recent notes conflict about shortness of breath.",
                    claim_type="change",
                    source_ids=["note-1", "note-2"],
                    support_status="supported",
                )
            ],
            sources=[
                ResponseSource(
                    id="note-1",
                    record_type="note",
                    display="Note source",
                    recorded_at="2026-04-30T07:00:00Z",
                    field_path="notes.body",
                    extracted_value="Shortness of breath improved overnight",
                ),
                ResponseSource(
                    id="note-2",
                    record_type="note",
                    display="Note source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="notes.body",
                    extracted_value="Shortness of breath worsened this morning",
                ),
            ],
            warnings=[],
            blocked_claims=[],
            verification_status="partial",
            trace_id="trace-test",
        )

        verified = verify_response(request, response)

        self.assertEqual(verified.answer, response.answer)
        self.assertEqual(verified.verification_status, "verified")
        self.assertEqual(verified.blocked_claims, [])

    def test_missing_data_adapter_gap_claim_does_not_get_rewritten(self):
        request = request_with_sources(
            "What is missing that I need before making clinical decisions?",
            [
                EvidenceSource(
                    id="allergy-none-9",
                    record_type="allergy",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.type=allergy",
                    value="No active allergies reported in retrieved OpenEMR allergy lists.",
                    metadata={"status": "absent"},
                ),
                EvidenceSource(
                    id="problem-91",
                    record_type="problem",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Diabetes",
                ),
            ],
            [
                AdapterStatus(adapter="problem_list", status="success"),
                AdapterStatus(adapter="allergies", status="success"),
                AdapterStatus(adapter="medications", status="unavailable", reason="No active meds found."),
                AdapterStatus(adapter="vitals", status="unavailable", reason="No vitals found."),
                AdapterStatus(adapter="labs", status="unavailable", reason="No labs found."),
                AdapterStatus(adapter="recent_notes", status="unavailable", reason="No notes found."),
            ],
        )
        response = AgentForgeResponse(
            answer=(
                "Before making clinical decisions, I would want current medications, recent vitals, "
                "recent labs, and recent notes. The retrieved payload confirms only a problem list "
                "and allergy status."
            ),
            sections=[],
            claims=[
                Claim(
                    id="claim-gap",
                    text="Current medications, recent vitals, recent labs, and recent notes are unavailable in the retrieved payload.",
                    claim_type="missing_data",
                    source_ids=[],
                    support_status="supported",
                ),
                Claim(
                    id="claim-allergy",
                    text="No active allergies reported in retrieved OpenEMR allergy lists.",
                    claim_type="allergy",
                    source_ids=["allergy-none-9"],
                    support_status="supported",
                ),
                Claim(
                    id="claim-problem",
                    text="Problem list includes Diabetes.",
                    claim_type="problem",
                    source_ids=["problem-91"],
                    support_status="supported",
                ),
            ],
            sources=[
                ResponseSource(
                    id="allergy-none-9",
                    record_type="allergy",
                    display="Absent Allergy source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.type=allergy",
                    extracted_value="No active allergies reported in retrieved OpenEMR allergy lists.",
                ),
                ResponseSource(
                    id="problem-91",
                    record_type="problem",
                    display="Problem source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    extracted_value="Diabetes",
                ),
            ],
            warnings=[],
            blocked_claims=[],
            verification_status="partial",
            trace_id="trace-test",
        )

        verified = verify_response(request, response)

        self.assertEqual(verified.verification_status, "partial")
        self.assertEqual(verified.answer, response.answer)
        self.assertEqual(verified.blocked_claims, [])
        self.assertIn("claim-gap", [claim.id for claim in verified.claims])

    def test_first_room_guidance_answer_is_not_rewritten_to_source_inventory(self):
        request = request_with_sources(
            "What should I ask the patient first when I enter the room?",
            [
                EvidenceSource(
                    id="problem-50",
                    record_type="problem",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Hypertension",
                ),
                EvidenceSource(
                    id="medication-list-43",
                    record_type="medication",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Amlodipine/Hydrochlorothiazide/Olmesartan",
                ),
                EvidenceSource(
                    id="allergy-none-5",
                    record_type="allergy",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.type=allergy",
                    value="No active allergies reported in retrieved OpenEMR allergy lists.",
                    metadata={"status": "absent"},
                ),
            ],
            [
                AdapterStatus(adapter="problem_list", status="success"),
                AdapterStatus(adapter="allergies", status="success"),
                AdapterStatus(adapter="medications", status="success"),
                AdapterStatus(adapter="recent_notes", status="unavailable", reason="No notes found."),
            ],
        )
        response = AgentForgeResponse(
            answer=(
                "First, ask: What brought you in today, and what symptoms are you having right now? "
                "Then confirm medication use and allergy history, because the chart shows hypertension, "
                "current antihypertensives, and no active allergies in the retrieved allergy list."
            ),
            sections=[],
            claims=[
                Claim(
                    id="claim-sequence",
                    text="Ask first about today's symptoms, then confirm medication use and allergy history.",
                    claim_type="guidance",
                    source_ids=[],
                    support_status="supported",
                ),
                Claim(
                    id="claim-problem",
                    text="The chart shows hypertension.",
                    claim_type="problem",
                    source_ids=["problem-50"],
                    support_status="supported",
                ),
                Claim(
                    id="claim-med",
                    text="Current listed medications include Amlodipine/Hydrochlorothiazide/Olmesartan.",
                    claim_type="medication",
                    source_ids=["medication-list-43"],
                    support_status="supported",
                ),
                Claim(
                    id="claim-allergy",
                    text="No active allergies reported in retrieved OpenEMR allergy lists.",
                    claim_type="allergy",
                    source_ids=["allergy-none-5"],
                    support_status="supported",
                ),
            ],
            sources=[
                ResponseSource(
                    id="problem-50",
                    record_type="problem",
                    display="Problem source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    extracted_value="Hypertension",
                ),
                ResponseSource(
                    id="medication-list-43",
                    record_type="medication",
                    display="Medication source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    extracted_value="Amlodipine/Hydrochlorothiazide/Olmesartan",
                ),
                ResponseSource(
                    id="allergy-none-5",
                    record_type="allergy",
                    display="Absent Allergy source",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.type=allergy",
                    extracted_value="No active allergies reported in retrieved OpenEMR allergy lists.",
                ),
            ],
            warnings=[],
            blocked_claims=[],
            verification_status="partial",
            trace_id="trace-test",
        )

        verified = verify_response(request, response)

        self.assertEqual(verified.answer, response.answer)
        self.assertEqual(verified.blocked_claims, [])
        self.assertIn("claim-sequence", [claim.id for claim in verified.claims])

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
