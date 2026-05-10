import unittest

from agentforge_sidecar.clinical_planner import classify_question, missing_required_adapters, plan_evidence
from agentforge_sidecar.schemas import (
    AdapterStatus,
    AgentForgeRequest,
    EvidenceSource,
    PatientContext,
    RoundingContextBundle,
    Scope,
)


def _request(message, sources, statuses=None):
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
        message=message,
        evidence_bundle=RoundingContextBundle(
            id="bundle-test",
            created_at="2026-04-30T09:59:00Z",
            patient_context=PatientContext(patient_id="123", encounter_id="456"),
            sources=sources,
            adapter_status=statuses or [],
        ),
    )


class ClinicalPlannerTest(unittest.TestCase):
    def test_classifies_physician_prompt_families(self):
        self.assertEqual(classify_question("What allergies do I need to know before ordering anything?"), "allergies")
        self.assertEqual(classify_question("Any active cardiac issues?"), "cardiac")
        self.assertEqual(classify_question("Medication reconciliation summary?"), "med_reconciliation")
        self.assertEqual(classify_question("What changed since last review?"), "change_since_review")
        self.assertEqual(classify_question("ASCVD risk?"), "cardiac")
        self.assertEqual(classify_question("Any contraindications before I prescribe?"), "allergies")
        self.assertEqual(classify_question("How should I think about this patient?"), "broad_brief")

    def test_allergy_plan_selects_allergies_and_risk_meds(self):
        request = _request(
            "What allergies do I need to know before ordering anything?",
            [
                EvidenceSource(
                    id="allergy-1",
                    record_type="allergy",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Allergy to eggs",
                ),
                EvidenceSource(
                    id="medication-1",
                    record_type="medication",
                    recorded_at="2026-04-30T08:01:00Z",
                    field_path="prescriptions.drug",
                    value="NDA020800 0.3 ML Epinephrine 1 MG/ML Auto-Injector",
                ),
                EvidenceSource(
                    id="problem-1",
                    record_type="problem",
                    recorded_at="2026-04-30T08:02:00Z",
                    field_path="lists.title",
                    value="Hyperlipidemia",
                ),
            ],
        )

        plan = plan_evidence(request)

        self.assertEqual(plan.answer_family, "allergies")
        self.assertIn("allergy-1", plan.selected_source_ids)
        self.assertIn("medication-1", plan.selected_source_ids)
        self.assertNotIn("problem-1", plan.selected_source_ids)

    def test_allergy_plan_does_not_select_synthetic_negative_evidence(self):
        request = _request(
            "What allergies do I need to know before ordering anything?",
            [],
            [AdapterStatus(adapter="allergies", status="unavailable", reason="No active allergy records found.")],
        )

        plan = plan_evidence(request)

        self.assertEqual(plan.answer_family, "allergies")
        self.assertEqual(list(plan.selected_source_ids), [])
        self.assertEqual(missing_required_adapters(request, plan), ["allergies"])

    def test_med_rec_plan_includes_historical_medications(self):
        request = _request(
            "Medication reconciliation summary?",
            [
                EvidenceSource(
                    id="medication-current",
                    record_type="medication",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="prescriptions.drug",
                    value="Loratadine 5 MG",
                    metadata={"status": "current"},
                ),
                EvidenceSource(
                    id="medication-history",
                    record_type="medication",
                    recorded_at="2026-04-01T08:00:00Z",
                    field_path="prescriptions.drug",
                    value="Prednisone",
                    metadata={"status": "historical"},
                ),
            ],
        )

        plan = plan_evidence(request)

        self.assertEqual(plan.answer_family, "med_reconciliation")
        self.assertEqual(list(plan.selected_source_ids), ["medication-current", "medication-history"])

    def test_medication_list_prompt_selects_uploaded_medication_list_facts(self):
        request = _request(
            "What is in the uploaded medication list?",
            [
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
            [
                AdapterStatus(adapter="agentforge_documents", status="success"),
                AdapterStatus(adapter="medications", status="unavailable", reason="No active medications found."),
            ],
        )

        plan = plan_evidence(request)

        self.assertEqual(classify_question(request.message), "document_facts")
        self.assertEqual(plan.answer_family, "document_facts")
        self.assertEqual(list(plan.selected_source_ids), ["document-fact-med-2", "document-fact-med-1"])
        self.assertEqual(missing_required_adapters(request, plan), [])

    def test_general_medication_prompt_can_use_uploaded_medication_list_when_adapter_is_empty(self):
        request = _request(
            "What medications is this patient on?",
            [
                EvidenceSource(
                    id="document-fact-med-1",
                    record_type="document_fact",
                    recorded_at="2026-05-05T01:25:58Z",
                    field_path="agentforge_extracted_facts.medication",
                    value="Metformin; Metformin 500 mg by mouth twice daily",
                    metadata={"document_type": "medication_list"},
                )
            ],
            [
                AdapterStatus(adapter="agentforge_documents", status="success"),
                AdapterStatus(adapter="medications", status="unavailable", reason="No active medications found."),
            ],
        )

        plan = plan_evidence(request)

        self.assertEqual(plan.answer_family, "med_reconciliation")
        self.assertEqual(list(plan.selected_source_ids), ["document-fact-med-1"])
        self.assertEqual(missing_required_adapters(request, plan), [])

    def test_general_medication_prompt_prefers_chart_prescriptions_after_writeback(self):
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
        request = _request(
            "What medications is this patient on?",
            [*chart_sources, *document_sources],
            [
                AdapterStatus(adapter="agentforge_documents", status="success"),
                AdapterStatus(adapter="medications", status="success"),
            ],
        )

        plan = plan_evidence(request)

        self.assertEqual(plan.answer_family, "med_reconciliation")
        self.assertEqual(len(plan.selected_source_ids), 3)
        self.assertFalse(any(source.id in plan.selected_source_ids for source in document_sources))
        self.assertTrue(all(source.id in plan.selected_source_ids for source in chart_sources))

    def test_broad_brief_keeps_all_matching_sources_across_categories(self):
        sources = [
            EvidenceSource(
                id=f"problem-{index}",
                record_type="problem",
                recorded_at="2026-04-30T08:00:00Z",
                field_path="lists.title",
                value=f"Problem {index}",
            )
            for index in range(1, 6)
        ]
        sources.extend(
            [
                EvidenceSource(
                    id=f"medication-{index}",
                    record_type="medication",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="prescriptions.drug",
                    value=f"Medication {index}",
                )
                for index in range(1, 4)
            ]
        )
        sources.extend(
            [
                EvidenceSource(
                    id=f"allergy-{index}",
                    record_type="allergy",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value=f"Allergy {index}",
                )
                for index in range(1, 5)
            ]
        )

        plan = plan_evidence(_request("Give me a one-minute pre-round summary for this patient.", sources))

        selected = set(plan.selected_source_ids)
        self.assertEqual(len([source_id for source_id in selected if source_id.startswith("problem-")]), 5)
        self.assertTrue({"medication-1", "medication-2", "medication-3"} <= selected)
        self.assertEqual(len([source_id for source_id in selected if source_id.startswith("allergy-")]), 4)

    def test_first_room_plan_keeps_problems_meds_and_allergies(self):
        request = _request(
            "What should I ask the patient first when I enter the room?",
            [
                EvidenceSource(
                    id=f"problem-{index}",
                    record_type="problem",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value=f"Problem {index}",
                )
                for index in range(1, 6)
            ]
            + [
                EvidenceSource(
                    id="medication-1",
                    record_type="medication",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="prescriptions.drug",
                    value="Loratadine 5 MG",
                ),
                EvidenceSource(
                    id="allergy-1",
                    record_type="allergy",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Allergy to eggs",
                ),
            ],
        )

        plan = plan_evidence(request)

        self.assertIn("medication-1", plan.selected_source_ids)
        self.assertIn("allergy-1", plan.selected_source_ids)
        self.assertEqual(len([source_id for source_id in plan.selected_source_ids if source_id.startswith("problem-")]), 5)

    def test_change_since_review_plan_selects_recent_notes(self):
        request = _request(
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
                EvidenceSource(
                    id="problem-1",
                    record_type="problem",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Pneumonia",
                ),
            ],
            [AdapterStatus(adapter="recent_notes", status="success")],
        )

        plan = plan_evidence(request)

        self.assertEqual(plan.answer_family, "change_since_review")
        self.assertEqual(list(plan.selected_source_ids), ["note-2", "note-1"])
        self.assertEqual(plan.required_adapters, ("recent_notes",))

    def test_name_and_last_visit_prompt_uses_chart_identity_and_encounters(self):
        request = _request(
            "What is this patient's name? When was their last visit?",
            [
                EvidenceSource(
                    id="patient-name-5",
                    record_type="demographic",
                    recorded_at="2026-05-10T14:00:00Z",
                    field_path="patient_data.fname_lname",
                    value="Big ol Bob",
                ),
                EvidenceSource(
                    id="document-fact-1112",
                    record_type="document_fact",
                    recorded_at="2026-05-10T14:05:00Z",
                    field_path="agentforge_extracted_facts.demographic",
                    value="Name; Sofia M. Reyes",
                    metadata={"document_type": "intake_form"},
                ),
                EvidenceSource(
                    id="encounter-20190130",
                    record_type="encounter",
                    recorded_at="2019-01-30 00:00:00",
                    field_path="form_encounter.date_reason",
                    value="2019-01-30; Follow-up encounter",
                ),
                EvidenceSource(
                    id="encounter-20190501",
                    record_type="encounter",
                    recorded_at="2019-05-01 00:00:00",
                    field_path="form_encounter.date_reason",
                    value="2019-05-01; General examination of patient (procedure)",
                ),
            ],
            [
                AdapterStatus(adapter="patient_snapshot", status="success"),
                AdapterStatus(adapter="encounters", status="success"),
                AdapterStatus(adapter="agentforge_documents", status="success"),
            ],
        )

        plan = plan_evidence(request)

        self.assertEqual(classify_question(request.message), "visit_history")
        self.assertEqual(plan.answer_family, "visit_history")
        self.assertEqual(plan.required_adapters, ("encounters",))
        self.assertIn("patient-name-5", plan.selected_source_ids)
        self.assertIn("encounter-20190501", plan.selected_source_ids)
        self.assertIn("encounter-20190130", plan.selected_source_ids)
        self.assertNotIn("document-fact-1112", plan.selected_source_ids)

    def test_intake_form_prompt_is_high_confidence_document_fact_plan(self):
        request = _request(
            "I need to know about this patient's intake form",
            [
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
                    id="document-fact-274",
                    record_type="document_fact",
                    recorded_at="2026-05-05T01:25:58Z",
                    field_path="agentforge_extracted_facts.pharmacy",
                    value="Phone Number; (217) 555-0160",
                    metadata={"document_type": "intake_form"},
                ),
                EvidenceSource(
                    id="document-fact-300",
                    record_type="document_fact",
                    recorded_at="2026-05-05T01:25:58Z",
                    field_path="agentforge_extracted_facts.lab_result",
                    value="Potassium; 5.8; abnormal high",
                    metadata={"document_type": "lab_pdf"},
                ),
            ],
            [AdapterStatus(adapter="agentforge_documents", status="success")],
        )

        plan = plan_evidence(request)

        self.assertEqual(classify_question(request.message), "document_facts")
        self.assertEqual(plan.answer_family, "document_facts")
        self.assertGreaterEqual(plan.confidence, 0.9)
        self.assertIn("document-fact-273", plan.selected_source_ids)
        self.assertIn("document-fact-274", plan.selected_source_ids)
        self.assertNotIn("document-fact-300", plan.selected_source_ids)
        self.assertNotIn("patient-name-1", plan.selected_source_ids)

    def test_intake_phone_prompt_selects_document_facts_without_tool_phase_need(self):
        request = _request(
            "give me all the phone numbers in the intake form",
            [
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
            [AdapterStatus(adapter="agentforge_documents", status="success")],
        )

        plan = plan_evidence(request)

        self.assertEqual(plan.answer_family, "document_facts")
        self.assertGreaterEqual(plan.confidence, 0.9)
        self.assertEqual(list(plan.selected_source_ids), ["document-fact-102", "document-fact-101"])

    def test_birthday_prompt_prefers_saved_document_dob_fact(self):
        request = _request(
            "what is this patient's birthday?",
            [
                EvidenceSource(
                    id="patient-dob-8",
                    record_type="demographic",
                    recorded_at="2026-05-10T13:25:58Z",
                    field_path="patient_data.DOB",
                    value="1971-06-08",
                ),
                EvidenceSource(
                    id="document-fact-799",
                    record_type="document_fact",
                    recorded_at="2026-05-10T13:26:00Z",
                    field_path="agentforge_extracted_facts.demographic",
                    value="Date of Birth; 06/08/1963",
                    metadata={
                        "document_type": "intake_form",
                        "citation": '{"field_or_chunk_id":"patient_demographics_dob","page_or_section":"Page 1"}',
                    },
                ),
                EvidenceSource(
                    id="document-fact-800",
                    record_type="document_fact",
                    recorded_at="2026-05-10T13:26:00Z",
                    field_path="agentforge_extracted_facts.demographic",
                    value="Email; robert@example.com",
                    metadata={"document_type": "intake_form"},
                ),
            ],
            [AdapterStatus(adapter="agentforge_documents", status="success")],
        )

        plan = plan_evidence(request)

        self.assertEqual(classify_question(request.message), "document_facts")
        self.assertIn("document-fact-799", plan.selected_source_ids)
        self.assertIn("patient-dob-8", plan.selected_source_ids)
        self.assertNotIn("document-fact-800", plan.selected_source_ids)

    def test_name_and_birthday_prompt_selects_each_saved_document_field(self):
        request = _request(
            "what is this patient's name and birthday?",
            [
                EvidenceSource(
                    id="patient-name-8",
                    record_type="demographic",
                    recorded_at="2026-05-10T13:25:58Z",
                    field_path="patient_data.fname_lname",
                    value="Adam J. Kowalski",
                ),
                EvidenceSource(
                    id="patient-dob-8",
                    record_type="demographic",
                    recorded_at="2026-05-10T13:25:58Z",
                    field_path="patient_data.DOB",
                    value="1971-06-08",
                ),
                EvidenceSource(
                    id="document-fact-862",
                    record_type="document_fact",
                    recorded_at="2026-05-10T13:26:00Z",
                    field_path="agentforge_extracted_facts.demographic",
                    value="Name; Adam J. Kowalski",
                    metadata={
                        "document_type": "intake_form",
                        "citation": '{"field_or_chunk_id":"patient_demographics_name","page_or_section":"Page 1"}',
                    },
                ),
                EvidenceSource(
                    id="document-fact-863",
                    record_type="document_fact",
                    recorded_at="2026-05-10T13:26:00Z",
                    field_path="agentforge_extracted_facts.demographic",
                    value="Date of Birth; 06/08/1971",
                    metadata={
                        "document_type": "intake_form",
                        "citation": '{"field_or_chunk_id":"patient_demographics_dob","page_or_section":"Page 1"}',
                    },
                ),
                EvidenceSource(
                    id="document-fact-864",
                    record_type="document_fact",
                    recorded_at="2026-05-10T13:26:00Z",
                    field_path="agentforge_extracted_facts.demographic",
                    value="Email; adam@example.com",
                    metadata={"document_type": "intake_form"},
                ),
            ],
            [AdapterStatus(adapter="agentforge_documents", status="success")],
        )

        plan = plan_evidence(request)

        self.assertEqual(classify_question(request.message), "document_facts")
        self.assertIn("document-fact-862", plan.selected_source_ids)
        self.assertIn("document-fact-863", plan.selected_source_ids)
        self.assertIn("patient-name-8", plan.selected_source_ids)
        self.assertIn("patient-dob-8", plan.selected_source_ids)
        self.assertNotIn("document-fact-864", plan.selected_source_ids)

    def test_lab_pdf_prompt_selects_extracted_lab_facts_without_lab_adapter(self):
        request = _request(
            "what can you tell me about this patient's labs?",
            [
                EvidenceSource(
                    id="document-fact-364",
                    record_type="document_fact",
                    recorded_at="2026-05-05T01:25:58Z",
                    field_path="agentforge_extracted_facts.lab_result",
                    value="Lymphocytes; 67; unit %; range <1; abnormal High",
                    metadata={"document_type": "lab_pdf"},
                ),
                EvidenceSource(
                    id="document-fact-365",
                    record_type="document_fact",
                    recorded_at="2026-05-05T01:25:58Z",
                    field_path="agentforge_extracted_facts.lab_result",
                    value="Metamyelocytes; 1; unit %; range <1; abnormal High",
                    metadata={"document_type": "lab_pdf"},
                ),
            ],
            [
                AdapterStatus(adapter="agentforge_documents", status="success"),
                AdapterStatus(adapter="labs", status="unavailable", reason="No recent lab results found."),
            ],
        )

        plan = plan_evidence(request)

        self.assertEqual(classify_question(request.message), "labs")
        self.assertEqual(plan.answer_family, "labs")
        self.assertIn("document-fact-364", plan.selected_source_ids)
        self.assertIn("document-fact-365", plan.selected_source_ids)
        self.assertEqual(missing_required_adapters(request, plan), [])

    def test_ascvd_synonym_selects_cardiometabolic_risk_evidence(self):
        request = _request(
            "ASCVD risk?",
            [
                EvidenceSource(
                    id="problem-lipid",
                    record_type="problem",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Hyperlipidemia",
                ),
                EvidenceSource(
                    id="problem-prediabetes",
                    record_type="problem",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Prediabetes",
                ),
                EvidenceSource(
                    id="vital-bp",
                    record_type="vital",
                    recorded_at="2026-04-30T08:01:00Z",
                    field_path="vitals.bp",
                    value="Blood pressure 137/89 mmHg",
                ),
            ],
        )

        plan = plan_evidence(request)

        self.assertEqual(plan.answer_family, "cardiac")
        self.assertGreaterEqual(plan.confidence, 0.8)
        self.assertIn("problem-lipid", plan.selected_source_ids)
        self.assertIn("problem-prediabetes", plan.selected_source_ids)
        self.assertIn("vital-bp", plan.selected_source_ids)

    def test_multi_intent_question_combines_secondary_family_sources(self):
        request = _request(
            "Can you summarize her cancer history and current meds?",
            [
                EvidenceSource(
                    id="problem-cancer",
                    record_type="problem",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Malignant neoplasm of breast",
                ),
                EvidenceSource(
                    id="medication-current",
                    record_type="medication",
                    recorded_at="2026-04-30T08:01:00Z",
                    field_path="prescriptions.drug",
                    value="Loratadine 5 MG",
                    metadata={"status": "current"},
                ),
                EvidenceSource(
                    id="allergy-egg",
                    record_type="allergy",
                    recorded_at="2026-04-30T08:02:00Z",
                    field_path="lists.title",
                    value="Egg allergy",
                ),
            ],
        )

        plan = plan_evidence(request)

        self.assertEqual(plan.answer_family, "oncology")
        self.assertIn("med_reconciliation", plan.secondary_families)
        self.assertIn("problem-cancer", plan.selected_source_ids)
        self.assertIn("medication-current", plan.selected_source_ids)
        self.assertNotIn("allergy-egg", plan.selected_source_ids)
        self.assertIn("medications", plan.needed_adapters)

    def test_unknown_specific_question_is_low_confidence_even_with_sources(self):
        plan = plan_evidence(
            _request(
                "What is the zebulon index?",
                [
                    EvidenceSource(
                        id="problem-1",
                        record_type="problem",
                        recorded_at="2026-04-30T08:00:00Z",
                        field_path="lists.title",
                        value="Pneumonia",
                    )
                ],
            )
        )

        self.assertEqual(plan.answer_family, "long_tail")
        self.assertLess(plan.confidence, 0.5)
        self.assertIn("problem-1", plan.selected_source_ids)

    def test_missing_required_adapters_is_question_scoped(self):
        request = _request(
            "Any active cardiac issues?",
            [
                EvidenceSource(
                    id="problem-1",
                    record_type="problem",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.title",
                    value="Hyperlipidemia",
                )
            ],
            [
                AdapterStatus(adapter="problem_list", status="success"),
                AdapterStatus(adapter="recent_notes", status="unavailable", reason="No notes found."),
            ],
        )

        self.assertEqual(missing_required_adapters(request), [])


if __name__ == "__main__":
    unittest.main()
