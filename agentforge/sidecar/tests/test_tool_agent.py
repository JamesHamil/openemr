import json
import unittest
from unittest.mock import patch

from agentforge_sidecar.schemas import (
    AdapterStatus,
    AgentForgeRequest,
    PatientContext,
    RoundingContextBundle,
    Scope,
    ToolPhaseResult,
    EvidenceSource,
)
from agentforge_sidecar.tool_agent import run_tool_phase, search_sources


class _FakeResponse:
    def __init__(self, response_id: str, output):
        self.id = response_id
        self.output = output


class _FakeParsedResponse:
    def __init__(self, parsed):
        self.output_parsed = parsed


class _FakeResponsesClient:
    def __init__(self):
        self.create_calls = []
        self.parse_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if len(self.create_calls) == 1:
            return _FakeResponse(
                "resp-1",
                [
                    {
                        "type": "function_call",
                        "name": "search_sources",
                        "call_id": "call-1",
                        "arguments": json.dumps({"query": "cardiac"}),
                    },
                    {
                        "type": "function_call",
                        "name": "search_sources",
                        "call_id": "call-2",
                        "arguments": json.dumps({"query": "cardiac"}),
                    },
                ],
            )
        return _FakeResponse(f"resp-{len(self.create_calls)}", [])

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        return _FakeParsedResponse(
            ToolPhaseResult(selected_source_ids=["problem-1"], drafted_claims=[], focus="cardiac issues")
        )


class _FakeClient:
    def __init__(self):
        self.responses = _FakeResponsesClient()


def _request() -> AgentForgeRequest:
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
        message="Any active cardiac issues?",
        evidence_bundle=RoundingContextBundle(
            id="bundle-test",
            created_at="2026-04-30T09:59:00Z",
            patient_context=PatientContext(patient_id="123", encounter_id="456"),
            sources=[
                EvidenceSource(
                    id="problem-1",
                    record_type="problem",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Hypertension",
                )
            ],
            adapter_status=[AdapterStatus(adapter="problem_list", status="success")],
        ),
    )


class ToolAgentTest(unittest.TestCase):
    def test_tool_call_budget_exhaustion_returns_outputs_for_all_calls(self):
        client = _FakeClient()
        request = _request()

        with patch("agentforge_sidecar.tool_agent.MAX_TOOL_CALLS", 1):
            plan, diagnostics = run_tool_phase(client, request, "gpt-4.1-mini")

        self.assertEqual(plan.selected_source_ids, ["problem-1"])
        self.assertEqual(diagnostics.tool_call_count, 1)
        self.assertEqual(diagnostics.fallback_reason, "tool_call_limit_reached")
        self.assertGreaterEqual(len(client.responses.create_calls), 3)

        tool_output_call = client.responses.create_calls[1]
        outputs = tool_output_call["input"]
        self.assertEqual({entry["call_id"] for entry in outputs}, {"call-1", "call-2"})

        overflow_output = next(entry for entry in outputs if entry["call_id"] == "call-2")
        decoded = json.loads(overflow_output["output"])
        self.assertFalse(decoded["success"])
        self.assertEqual(decoded["error"], "tool_call_limit_reached")

    def test_search_sources_major_issues_prefers_problem_records(self):
        request = _request().model_copy(
            update={
                "evidence_bundle": _request().evidence_bundle.model_copy(
                    update={
                        "sources": [
                            EvidenceSource(
                                id="patient-sex-1",
                                record_type="demographic",
                                recorded_at="2026-04-30T08:00:00Z",
                                field_path="patient_data.sex",
                                value="Male",
                            ),
                            EvidenceSource(
                                id="problem-9",
                                record_type="problem",
                                recorded_at="2026-04-30T08:05:00Z",
                                field_path="lists.title",
                                value="Prediabetes",
                            ),
                        ]
                    }
                )
            }
        )

        matches = search_sources(request, "what major issues does this patient have?", [], 5)
        self.assertTrue(matches)
        self.assertEqual(matches[0]["record_type"], "problem")
        self.assertEqual(matches[0]["id"], "problem-9")

    def test_search_sources_allergy_focus_prefers_allergy_sources(self):
        request = _request().model_copy(
            update={
                "evidence_bundle": _request().evidence_bundle.model_copy(
                    update={
                        "sources": [
                            EvidenceSource(
                                id="problem-5",
                                record_type="problem",
                                recorded_at="2026-04-30T08:00:00Z",
                                field_path="lists.title",
                                value="Hypertension",
                            ),
                            EvidenceSource(
                                id="allergy-2",
                                record_type="allergy",
                                recorded_at="2026-04-30T08:02:00Z",
                                field_path="lists.title",
                                value="Allergy to eggs",
                            ),
                        ]
                    }
                )
            }
        )

        matches = search_sources(request, "what allergies should I know?", [], 5)
        self.assertTrue(matches)
        self.assertEqual(matches[0]["record_type"], "allergy")
        self.assertEqual(matches[0]["id"], "allergy-2")


if __name__ == "__main__":
    unittest.main()
