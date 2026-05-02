from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "agentforge" / "sidecar"
sys.path.insert(0, str(SIDECAR))

from agentforge_sidecar.mock_provider import mock_response  # noqa: E402
from agentforge_sidecar.schemas import (  # noqa: E402
    AdapterStatus,
    AgentForgeRequest,
    Claim,
    EvidenceSource,
    PatientContext,
    RoundingContextBundle,
    Scope,
)
from agentforge_sidecar.service import handle_chat  # noqa: E402
from agentforge_sidecar.settings import load_settings  # noqa: E402
from agentforge_sidecar.verifier import verify_response  # noqa: E402


LIVE_CONCEPTS = {
    "lab_result_objective_data": ["pneumonia", "potassium", "abnormal_lab"],
    "conflicting_notes": ["change_or_conflict", "improved", "worsened"],
    "physician_prompt_pre_round_summary": ["problem_evidence", "allergy_evidence", "medication_evidence", "missing_gap"],
    "physician_prompt_allergy_ordering": ["allergies", "epinephrine", "drug_allergy_status", "severity_or_trigger"],
    "physician_prompt_active_cardiac": ["cardiac_or_risk", "vital_or_confirm"],
    "physician_prompt_endocrine_metabolic": ["cardiometabolic_risk", "labs_review"],
    "physician_prompt_oncology_history": ["oncology_history", "oncology_status_followup"],
    "physician_prompt_red_flags": ["bullet_wound", "miscarriage", "verify_status"],
    "physician_prompt_med_reconciliation": ["current_meds", "active_or_legacy"],
    "physician_prompt_meds_for_allergy_management": ["allergy_med", "epinephrine", "antihistamine"],
    "physician_prompt_ask_patient_first": ["symptoms_first", "allergy_history", "medication_use", "diagnosis_status"],
    "physician_prompt_missing_before_decisions": ["missing_data", "labs_or_notes", "confirm_or_review"],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AgentForge smoke evals.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the eval results as JSON instead of the default human-readable report.",
    )
    args = parser.parse_args(argv)

    cases = json.loads((Path(__file__).with_name("smoke_cases.json")).read_text())
    eval_mode = os.getenv("AGENTFORGE_EVAL_MODE", "mock").strip().lower()
    if eval_mode not in {"mock", "live"}:
        eval_mode = "mock"
    results = []
    failed = 0

    for case in cases:
        request = build_request(case)
        if case.get("force_unsupported_claim") or case.get("force_all_claims_blocked"):
            response = mock_response(request, f"eval-{case['id']}")
            if case.get("force_all_claims_blocked"):
                blocked = []
                for index, claim in enumerate(response.claims, start=1):
                    blocked.append(
                        claim.model_copy(
                            update={
                                "id": f"claim-unsupported-{index}",
                                "text": "The retrieved source includes diabetes.",
                            }
                        )
                    )
                response = response.model_copy(update={"claims": blocked})
            else:
                response.claims[0] = Claim(
                    id="claim-unsupported",
                    text="The retrieved source includes diabetes.",
                    claim_type="problem",
                    source_ids=[response.claims[0].source_ids[0]],
                    support_status="supported",
                )
            response = verify_response(request, response)
        else:
            response, _trace = handle_chat(request, replace(load_settings(), mode="real" if eval_mode == "live" else "mock"))

        passed, failure_reasons = evaluate_case(case, response, eval_mode)

        if not passed:
            failed += 1

        results.append(
            {
                "id": case["id"],
                "input": case["message"],
                "expected": case["expected_status"],
                "actual": response.verification_status,
                "output": response.answer,
                "warnings": [warning.code for warning in response.warnings],
                "blocked_claims": response.blocked_claims,
                "sections": [section.id for section in response.sections],
                "source_types": [source.record_type for source in response.sources],
                "eval_mode": eval_mode,
                "passed": passed,
                "failure_reasons": failure_reasons,
            }
        )

    payload = {"passed": len(results) - failed, "failed": failed, "results": results}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(payload, eval_mode))
    return 1 if failed else 0


def format_report(payload: dict, eval_mode: str) -> str:
    lines = [
        f"AgentForge evals ({eval_mode} mode)",
        f"Summary: {payload['passed']} passed, {payload['failed']} failed",
        "",
    ]
    for result in payload["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        warnings = ", ".join(result["warnings"]) if result["warnings"] else "none"
        blocked_count = len(result["blocked_claims"])
        source_types = ", ".join(result["source_types"]) if result["source_types"] else "none"
        lines.extend(
            [
                f"[{status}] {result['id']}",
                f"  Input: {result['input']}",
                f"  Expected: {result['expected']} | Actual: {result['actual']}",
                f"  Failure reasons: {', '.join(result['failure_reasons']) if result['failure_reasons'] else 'none'}",
                f"  Warnings: {warnings}",
                f"  Sources: {source_types}",
                f"  Blocked claims: {blocked_count}",
                f"  Output: {result['output']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def evaluate_case(case: dict, response, eval_mode: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    answer = response.answer.lower()

    if response.verification_status != case["expected_status"]:
        reasons.append(f"status expected {case['expected_status']} got {response.verification_status}")
    if case.get("expected_warning_code") and not any(
        warning.code == case["expected_warning_code"] for warning in response.warnings
    ):
        reasons.append(f"missing warning {case['expected_warning_code']}")
    if case.get("expected_blocked") and not response.blocked_claims:
        reasons.append("expected blocked claims")
    if case.get("expected_min_sections") is not None and len(response.sections) < int(case["expected_min_sections"]):
        reasons.append(f"expected at least {case['expected_min_sections']} sections")
    if case.get("expected_source_record_type") and not any(
        source.record_type == case["expected_source_record_type"] for source in response.sources
    ):
        reasons.append(f"missing source type {case['expected_source_record_type']}")

    if eval_mode == "live" and case["id"] in LIVE_CONCEPTS:
        for concept in LIVE_CONCEPTS[case["id"]]:
            if not _concept_present(concept, answer):
                reasons.append(f"missing live concept {concept}")
    else:
        if case.get("expected_answer_contains") and case["expected_answer_contains"].lower() not in answer:
            reasons.append(f"answer missing phrase {case['expected_answer_contains']!r}")
        if case.get("expected_answer_contains_all"):
            for phrase in case["expected_answer_contains_all"]:
                if phrase.lower() not in answer:
                    reasons.append(f"answer missing phrase {phrase!r}")

    if case.get("expected_answer_not_contains") and case["expected_answer_not_contains"].lower() in answer:
        reasons.append(f"answer contains forbidden phrase {case['expected_answer_not_contains']!r}")
    if case.get("expected_answer_not_contains_any"):
        for phrase in case["expected_answer_not_contains_any"]:
            if phrase.lower() in answer:
                reasons.append(f"answer contains forbidden phrase {phrase!r}")
    if case.get("expected_answer_starts_with") and not answer.startswith(case["expected_answer_starts_with"].lower()):
        reasons.append(f"answer does not start with {case['expected_answer_starts_with']!r}")
    return not reasons, reasons


def _concept_present(concept: str, answer: str) -> bool:
    concept_terms = {
        "abnormal_lab": (("abnormal", "elevated", "high", "hyperkalemia"),),
        "active_or_legacy": (("active", "current"), ("legacy", "historical", "past")),
        "allergies": (("allergy", "allergies"),),
        "allergy_evidence": (("allergy", "allergies"),),
        "allergy_history": (("allergy", "allergies", "reaction"),),
        "allergy_med": (("allergy", "allergic", "antihistamine", "loratadine"),),
        "antihistamine": (("loratadine", "antihistamine"),),
        "bullet_wound": (("bullet",),),
        "cardiac_or_risk": (("cardiac", "cardiovascular", "hypertension", "heart"),),
        "cardiometabolic_risk": (("cardiometabolic",), ("prediabetes", "hyperlipidemia")),
        "change_or_conflict": (("changed", "change", "conflict", "conflicting", "improved", "worsened"),),
        "confirm_or_review": (("confirm", "review", "verify", "needed"),),
        "current_meds": (("current", "listed", "medication", "medications", "prescription", "prescriptions"),),
        "diagnosis_status": (("diagnosis", "diagnoses", "problem", "problems", "condition", "status", "concerns"),),
        "drug_allergy_status": (("drug", "medication"), ("no documented", "not noted", "not identified", "no clear")),
        "endocrine_metabolic": (("prediabetes", "hyperlipidemia", "metabolic"),),
        "epinephrine": (("epinephrine", "auto-injector", "autoinjector"),),
        "improved": (("improved",),),
        "labs_or_notes": (("lab", "labs", "note", "notes", "vital", "vitals"),),
        "labs_review": (("lab", "labs", "glucose", "lipid"), ("review", "check", "assess")),
        "medication_evidence": (("medication", "medications", "med", "meds", "loratadine", "liletta", "epinephrine"),),
        "medication_use": (("medication", "medications", "med", "meds"),),
        "missing_data": (("missing", "unavailable", "not available", "needed"),),
        "missing_gap": (("missing", "unavailable", "not available", "confirm", "review"),),
        "miscarriage": (("miscarriage",),),
        "oncology_history": (("malignant", "neoplasm", "breast", "cancer", "oncology"),),
        "oncology_status_followup": (("status", "active", "history", "timeline", "follow-up", "follow up", "oncology"),),
        "pneumonia": (("pneumonia",),),
        "potassium": (("potassium", "k+"),),
        "problem_evidence": (("problem", "problems", "diagnosis", "diagnoses", "active issues"),),
        "severity_or_trigger": (("severity", "trigger", "severe", "reaction", "reactions"),),
        "symptoms_first": (("symptom", "symptoms", "concern", "concerns", "brought you in", "feeling"),),
        "verify_status": (("verify", "confirm", "clarify"), ("active", "historical", "resolved", "current", "status")),
        "vital_or_confirm": (("vital", "blood pressure", "bp", "137/89", "confirm", "review"),),
        "worsened": (("worsened", "worse"),),
    }
    groups = concept_terms.get(concept, ((concept,),))
    return all(any(term in answer for term in group) for group in groups)


def build_request(case: dict) -> AgentForgeRequest:
    sources = [
        EvidenceSource(
            id=source_id,
            record_type=record_type,
            recorded_at="2026-04-29T08:00:00Z",
            field_path=field_path,
            value=value,
        )
        for source_id, record_type, field_path, value in case["sources"]
    ]
    adapter_status = [
        AdapterStatus(adapter=adapter, status=status, reason=reason)
        for adapter, status, reason in case["adapter_status"]
    ]
    bundle = RoundingContextBundle(
        id=f"bundle-{case['id']}",
        created_at="2026-04-29T08:01:00Z",
        patient_context=PatientContext(patient_id="demo-patient", encounter_id="demo-encounter"),
        sources=sources,
        adapter_status=adapter_status,
    )
    return AgentForgeRequest(
        schema_version="agentforge.request.v1",
        request_id=f"req-{case['id']}",
        conversation_id="eval-conversation",
        expires_at="2026-04-29T08:06:00Z",
        purpose="patient_rounding_brief",
        scope=Scope(
            user_hash="eval-user",
            patient_hash="eval-patient",
            encounter_hash="eval-encounter",
            evidence_bundle_id=bundle.id,
        ),
        message=case["message"],
        evidence_bundle=bundle,
    )


if __name__ == "__main__":
    raise SystemExit(main())
