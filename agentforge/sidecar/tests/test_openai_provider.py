import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agentforge_sidecar.clinical_planner import plan_evidence
from agentforge_sidecar.openai_provider import (
    ModelAgentForgeResponse,
    ModelResponseSource,
    ModelVerificationResult,
    _fallback_answer_for_plan,
    _limit_response,
    _model_verify_and_repair,
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

    def parse(self, **_kwargs):
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
        self.assertEqual(diagnostics.input_tokens, 180)
        self.assertEqual(diagnostics.output_tokens, 25)

    def test_openai_response_uses_model_tool_phase_for_low_confidence_plan(self):
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
                response, diagnostics = openai_response(request, "trace-test", Settings(mode="real"))

        run_tool_phase.assert_called_once()
        self.assertEqual(response.verification_status, "verified")
        self.assertEqual(diagnostics.source_selection_mode, "model_tool_phase")
        self.assertEqual(diagnostics.tool_call_count, 1)
        self.assertEqual(diagnostics.planning_latency_ms, 123)

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
            settings=Settings(mode="real"),
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


if __name__ == "__main__":
    unittest.main()
