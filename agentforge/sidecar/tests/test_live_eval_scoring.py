import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))

from run_evals import _concept_present  # noqa: E402


class LiveEvalScoringTest(unittest.TestCase):
    def test_cardiometabolic_concept_accepts_equivalent_clinical_wording(self):
        answer = (
            "The patient presents with endocrine and metabolic risk factors including "
            "Prediabetes and Hyperlipidemia. These increase her risk for type 2 diabetes "
            "and cardiovascular disease."
        ).lower()

        self.assertTrue(_concept_present("cardiometabolic_risk", answer))

    def test_missing_data_concept_accepts_adapter_specific_fallback(self):
        answer = "Missing retrieved data includes labs and recent notes; confirm in chart before final decisions."

        self.assertTrue(_concept_present("missing_data", answer.lower()))
        self.assertTrue(_concept_present("labs_or_notes", answer.lower()))


if __name__ == "__main__":
    unittest.main()
