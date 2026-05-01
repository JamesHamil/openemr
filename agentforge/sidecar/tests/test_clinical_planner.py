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

    def test_allergy_plan_selects_negative_allergy_evidence(self):
        request = _request(
            "What allergies do I need to know before ordering anything?",
            [
                EvidenceSource(
                    id="allergy-none-123",
                    record_type="allergy",
                    recorded_at="2026-04-30T08:00:00Z",
                    field_path="lists.type=allergy",
                    value="No active allergies reported in retrieved OpenEMR allergy lists.",
                    metadata={"status": "absent"},
                ),
            ],
            [AdapterStatus(adapter="allergies", status="success")],
        )

        plan = plan_evidence(request)

        self.assertEqual(plan.answer_family, "allergies")
        self.assertEqual(list(plan.selected_source_ids), ["allergy-none-123"])
        self.assertEqual(missing_required_adapters(request, plan), [])

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
