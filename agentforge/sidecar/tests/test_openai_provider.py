import unittest

from agentforge_sidecar.clinical_planner import plan_evidence
from agentforge_sidecar.openai_provider import (
    ModelAgentForgeResponse,
    ModelVerificationResult,
    _limit_response,
    _model_verify_and_repair,
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
)
from agentforge_sidecar.settings import Settings


class _Parsed:
    def __init__(self, output):
        self.output_parsed = output


class _FakeResponses:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def parse(self, **_kwargs):
        return _Parsed(self.outputs.pop(0))


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
                repaired,
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


if __name__ == "__main__":
    unittest.main()
