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
from agentforge_sidecar.tool_agent import (
    check_allergy_conflicts,
    execute_tool,
    get_document_facts,
    run_tool_phase,
    search_sources,
    summarize_by_type,
)


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

    def test_search_sources_lab_focus_includes_extracted_lab_pdf_facts(self):
        request = _request().model_copy(
            update={
                "evidence_bundle": _request().evidence_bundle.model_copy(
                    update={
                        "sources": [
                            EvidenceSource(
                                id="document-fact-23",
                                record_type="document_fact",
                                recorded_at="2026-04-30T08:10:00Z",
                                field_path="agentforge_extracted_facts.Hemoglobin",
                                value="Hemoglobin; 15.1; unit g/dL; abnormal High",
                                metadata={"document_type": "lab_pdf", "openemr_document_id": "7"},
                            ),
                            EvidenceSource(
                                id="problem-1",
                                record_type="problem",
                                recorded_at="2026-04-30T08:00:00Z",
                                field_path="lists.title",
                                value="Hypertension",
                            ),
                        ]
                    }
                )
            }
        )

        matches = search_sources(request, "tell me about this patient's labs", ["lab"], 5)

        self.assertTrue(matches)
        self.assertEqual(matches[0]["record_type"], "document_fact")
        self.assertEqual(matches[0]["id"], "document-fact-23")

    def test_search_sources_lab_focus_prefers_lab_facts_over_newer_form_facts(self):
        request = _request().model_copy(
            update={
                "evidence_bundle": _request().evidence_bundle.model_copy(
                    update={
                        "sources": [
                            EvidenceSource(
                                id="document-fact-intake-name",
                                record_type="document_fact",
                                recorded_at="2026-04-30T09:00:00Z",
                                field_path="agentforge_extracted_facts.Name",
                                value="Name; Jordan M. Rivera",
                                metadata={
                                    "document_type": "lab_pdf",
                                    "filename": "filled_patient_intake_form_dummy.pdf",
                                },
                            ),
                            EvidenceSource(
                                id="document-fact-cbc-platelets",
                                record_type="document_fact",
                                recorded_at="2026-04-30T08:00:00Z",
                                field_path="agentforge_extracted_facts.Platelet Count",
                                value="Platelet Count; 52; abnormal Low",
                                metadata={
                                    "document_type": "lab_pdf",
                                    "filename": "9109 Abn Sample Report 20180503 CBC with Differential Blood.pdf",
                                },
                            ),
                        ]
                    }
                )
            }
        )

        matches = search_sources(request, "How are this patient's labs?", ["lab"], 5)

        self.assertTrue(matches)
        self.assertEqual(matches[0]["id"], "document-fact-cbc-platelets")

    def test_summarize_by_type_returns_counts_and_representative_sources(self):
        request = _request().model_copy(
            update={
                "evidence_bundle": _request().evidence_bundle.model_copy(
                    update={
                        "sources": [
                            EvidenceSource(
                                id="problem-1",
                                record_type="problem",
                                recorded_at="2026-04-30T08:00:00Z",
                                field_path="lists.title",
                                value="Hypertension",
                            ),
                            EvidenceSource(
                                id="problem-2",
                                record_type="problem",
                                recorded_at="2026-04-30T08:05:00Z",
                                field_path="lists.title",
                                value="Prediabetes",
                            ),
                            EvidenceSource(
                                id="allergy-1",
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

        summary = summarize_by_type(request, ["problem"], 1)

        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["record_type"], "problem")
        self.assertEqual(summary[0]["count"], 2)
        self.assertEqual(summary[0]["representative_sources"][0]["id"], "problem-2")

    def test_check_allergy_conflicts_surfaces_overlap_and_allergy_management_meds(self):
        request = _request().model_copy(
            update={
                "evidence_bundle": _request().evidence_bundle.model_copy(
                    update={
                        "sources": [
                            EvidenceSource(
                                id="allergy-1",
                                record_type="allergy",
                                recorded_at="2026-04-30T08:00:00Z",
                                field_path="lists.title",
                                value="Penicillin allergy",
                            ),
                            EvidenceSource(
                                id="medication-1",
                                record_type="medication",
                                recorded_at="2026-04-30T08:05:00Z",
                                field_path="prescriptions.drug",
                                value="Penicillin VK",
                            ),
                            EvidenceSource(
                                id="medication-2",
                                record_type="medication",
                                recorded_at="2026-04-30T08:06:00Z",
                                field_path="prescriptions.drug",
                                value="Loratadine 5 MG",
                            ),
                        ]
                    }
                )
            }
        )

        payload = check_allergy_conflicts(request)

        self.assertIn("penicillin", payload["potential_conflict_terms"])
        self.assertEqual(payload["review_pairs"][0]["medication_source_id"], "medication-1")
        self.assertEqual(payload["allergy_management_meds"][0]["id"], "medication-2")

    def test_execute_tool_supports_new_summary_and_allergy_tools(self):
        request = _request()

        summary = execute_tool(request, "summarize_by_type", json.dumps({"record_types": ["problem"]}))
        conflicts = execute_tool(request, "check_allergy_conflicts", "{}")

        self.assertTrue(summary.success)
        self.assertEqual(summary.tool, "summarize_by_type")
        self.assertIn("summary", summary.payload)
        self.assertTrue(conflicts.success)
        self.assertEqual(conflicts.tool, "check_allergy_conflicts")

    def test_get_document_facts_phone_group_returns_all_intake_phone_sources(self):
        request = _request().model_copy(
            update={
                "evidence_bundle": _request().evidence_bundle.model_copy(
                    update={"sources": _intake_document_sources()}
                )
            }
        )

        facts = get_document_facts(request, document_type="intake_form", field_group="phone_numbers", limit=8)

        self.assertEqual(
            [fact["id"] for fact in facts],
            ["document-fact-101", "document-fact-102", "document-fact-103"],
        )
        self.assertEqual(facts[0]["field_id"], "phone")
        self.assertEqual(facts[2]["label"], "Pharmacy Phone")

    def test_get_document_facts_filters_by_explicit_fields(self):
        request = _request().model_copy(
            update={
                "evidence_bundle": _request().evidence_bundle.model_copy(
                    update={"sources": _intake_document_sources()}
                )
            }
        )

        facts = get_document_facts(
            request,
            document_type="intake_form",
            fields=["emergency_contact_phone"],
            limit=8,
        )

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["id"], "document-fact-102")

    def test_get_document_facts_unknown_group_returns_empty_result(self):
        request = _request().model_copy(
            update={
                "evidence_bundle": _request().evidence_bundle.model_copy(
                    update={"sources": _intake_document_sources()}
                )
            }
        )

        facts = get_document_facts(request, document_type="intake_form", field_group="nope", limit=8)

        self.assertEqual(facts, [])

    def test_execute_tool_supports_document_fact_tool(self):
        request = _request().model_copy(
            update={
                "evidence_bundle": _request().evidence_bundle.model_copy(
                    update={"sources": _intake_document_sources()}
                )
            }
        )

        result = execute_tool(
            request,
            "get_document_facts",
            json.dumps({"document_type": "intake_form", "field_group": "phone_numbers"}),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.tool, "get_document_facts")
        self.assertEqual(len(result.payload["facts"]), 3)

def _intake_document_sources():
    return [
        EvidenceSource(
            id="document-fact-101",
            record_type="document_fact",
            recorded_at="2026-05-05T01:25:58Z",
            field_path="agentforge_extracted_facts.demographic",
            value="Patient Phone; (217) 555-0198",
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
            value="Pharmacy Phone; (217) 555-0160",
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
    ]


if __name__ == "__main__":
    unittest.main()
