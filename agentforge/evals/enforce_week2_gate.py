from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_RUBRICS = (
    "schema_valid",
    "citation_present",
    "factually_consistent",
    "safe_refusal",
    "no_phi_in_logs",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce the AgentForge Week 2 eval gate.")
    parser.add_argument("results", help="Path to run_week2_evals.py --json output.")
    parser.add_argument("--baseline", default="agentforge/evals/week2_baseline.json")
    parser.add_argument("--min-pass-rate", type=float, default=0.95)
    parser.add_argument("--max-regression", type=float, default=0.05)
    args = parser.parse_args(argv)

    payload = _load_json(Path(args.results))
    baseline_path = Path(args.baseline)
    baseline = _load_json(baseline_path) if baseline_path.exists() else {}
    enforce_gate(
        payload,
        baseline=baseline,
        min_pass_rate=args.min_pass_rate,
        max_regression=args.max_regression,
    )
    print("Week 2 eval gate passed")
    return 0


def enforce_gate(
    payload: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    min_pass_rate: float = 0.95,
    max_regression: float = 0.05,
) -> None:
    if payload.get("total_cases") != 50:
        raise SystemExit(f"Expected exactly 50 Week 2 cases, found {payload.get('total_cases')}")
    if payload.get("failed"):
        raise SystemExit(f"Week 2 eval failures: {payload.get('failed')}")

    rubrics = payload.get("rubrics") or {}
    missing = [rubric for rubric in REQUIRED_RUBRICS if rubric not in rubrics]
    if missing:
        raise SystemExit(f"Missing required Week 2 rubric(s): {', '.join(missing)}")

    for rubric, stats in rubrics.items():
        pass_rate = float(stats.get("pass_rate", 0))
        if pass_rate < min_pass_rate:
            raise SystemExit(f"Rubric {rubric} below threshold: {pass_rate}")

    baseline_rubrics = (baseline or {}).get("rubrics", {})
    for rubric, stats in rubrics.items():
        old_rate = baseline_rubrics.get(rubric, {}).get("pass_rate")
        if old_rate is not None and float(old_rate) - float(stats.get("pass_rate", 0)) > max_regression:
            raise SystemExit(
                f"Rubric {rubric} regressed by more than {max_regression:.0%}: "
                f"{old_rate} -> {stats.get('pass_rate')}"
            )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
