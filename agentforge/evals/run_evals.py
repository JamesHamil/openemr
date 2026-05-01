from __future__ import annotations

import argparse
import json
import os
import sys
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
from agentforge_sidecar.settings import Settings  # noqa: E402
from agentforge_sidecar.verifier import verify_response  # noqa: E402


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
            response, _trace = handle_chat(request, Settings(mode="real" if eval_mode == "live" else "mock"))

        passed = response.verification_status == case["expected_status"]
        if case.get("expected_warning_code"):
            passed = passed and any(warning.code == case["expected_warning_code"] for warning in response.warnings)
        if case.get("expected_blocked"):
            passed = passed and bool(response.blocked_claims)
        if case.get("expected_min_sections") is not None:
            passed = passed and len(response.sections) >= int(case["expected_min_sections"])
        if case.get("expected_source_record_type"):
            passed = passed and any(
                source.record_type == case["expected_source_record_type"] for source in response.sources
            )
        if case.get("expected_answer_contains"):
            passed = passed and case["expected_answer_contains"].lower() in response.answer.lower()
        if case.get("expected_answer_not_contains"):
            passed = passed and case["expected_answer_not_contains"].lower() not in response.answer.lower()
        if case.get("expected_answer_contains_all"):
            passed = passed and all(
                phrase.lower() in response.answer.lower() for phrase in case["expected_answer_contains_all"]
            )
        if case.get("expected_answer_not_contains_any"):
            passed = passed and all(
                phrase.lower() not in response.answer.lower() for phrase in case["expected_answer_not_contains_any"]
            )
        if case.get("expected_answer_starts_with"):
            passed = passed and response.answer.lower().startswith(case["expected_answer_starts_with"].lower())
        if case.get("expected_answer_max_words") is not None:
            passed = passed and len(response.answer.split()) <= int(case["expected_answer_max_words"])

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
                f"  Warnings: {warnings}",
                f"  Sources: {source_types}",
                f"  Blocked claims: {blocked_count}",
                f"  Output: {result['output']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


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
