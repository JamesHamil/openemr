from __future__ import annotations

import json
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


def main() -> int:
    cases = json.loads((Path(__file__).with_name("smoke_cases.json")).read_text())
    results = []
    failed = 0

    for case in cases:
        request = build_request(case)
        if case.get("force_unsupported_claim"):
            response = mock_response(request, f"eval-{case['id']}")
            response.claims[0] = Claim(
                id="claim-unsupported",
                text="The retrieved source includes diabetes.",
                claim_type="problem",
                source_ids=[response.claims[0].source_ids[0]],
                support_status="supported",
            )
            response = verify_response(request, response)
        else:
            response, _trace = handle_chat(request, Settings(mode="mock"))

        passed = response.verification_status == case["expected_status"]
        if case.get("expected_warning_code"):
            passed = passed and any(warning.code == case["expected_warning_code"] for warning in response.warnings)
        if case.get("expected_blocked"):
            passed = passed and bool(response.blocked_claims)

        if not passed:
            failed += 1

        results.append(
            {
                "id": case["id"],
                "expected": case["expected_status"],
                "actual": response.verification_status,
                "warnings": [warning.code for warning in response.warnings],
                "blocked_claims": response.blocked_claims,
                "passed": passed,
            }
        )

    print(json.dumps({"passed": len(results) - failed, "failed": failed, "results": results}, indent=2))
    return 1 if failed else 0


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
