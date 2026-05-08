import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))

from enforce_week2_gate import enforce_gate  # noqa: E402


def _payload() -> dict:
    rubrics = {
        "schema_valid": {"passed": 50, "total": 50, "pass_rate": 1.0},
        "citation_present": {"passed": 50, "total": 50, "pass_rate": 1.0},
        "factually_consistent": {"passed": 50, "total": 50, "pass_rate": 1.0},
        "safe_refusal": {"passed": 50, "total": 50, "pass_rate": 1.0},
        "no_phi_in_logs": {"passed": 50, "total": 50, "pass_rate": 1.0},
    }
    return {"total_cases": 50, "failed": 0, "rubrics": rubrics}


class Week2EvalGateTest(unittest.TestCase):
    def test_accepts_passing_required_rubrics(self):
        enforce_gate(_payload(), baseline=_payload())

    def test_requires_all_assignment_rubrics(self):
        payload = _payload()
        del payload["rubrics"]["no_phi_in_logs"]

        with self.assertRaises(SystemExit):
            enforce_gate(payload, baseline=_payload())

    def test_rejects_category_below_threshold(self):
        payload = _payload()
        payload["rubrics"]["citation_present"]["pass_rate"] = 0.94

        with self.assertRaises(SystemExit):
            enforce_gate(payload, baseline=_payload())

    def test_rejects_more_than_five_percent_regression(self):
        payload = _payload()
        payload["rubrics"]["safe_refusal"]["pass_rate"] = 0.94

        with self.assertRaises(SystemExit):
            enforce_gate(payload, baseline=_payload(), min_pass_rate=0.90)


if __name__ == "__main__":
    unittest.main()
