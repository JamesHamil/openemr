import os
import unittest
from unittest.mock import patch

from agentforge_sidecar.settings import load_settings


class SettingsTest(unittest.TestCase):
    def test_real_mode_uses_gpt_54_mini_low_reasoning_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings()

        self.assertEqual(settings.mode, "real")
        self.assertEqual(settings.model, "gpt-5.4-mini")
        self.assertEqual(settings.reasoning_effort, "low")
        self.assertEqual(settings.reasoning, {"effort": "low"})

    def test_model_and_reasoning_can_be_overridden(self):
        with patch.dict(
            os.environ,
            {
                "AGENTFORGE_OPENAI_MODEL": "gpt-5.4-mini",
                "AGENTFORGE_REASONING_EFFORT": "medium",
            },
            clear=True,
        ):
            settings = load_settings()

        self.assertEqual(settings.model, "gpt-5.4-mini")
        self.assertEqual(settings.reasoning_effort, "medium")
        self.assertEqual(settings.reasoning, {"effort": "medium"})

    def test_invalid_mode_and_reasoning_fail_to_live_defaults(self):
        with patch.dict(
            os.environ,
            {
                "AGENTFORGE_MODE": "surprise",
                "AGENTFORGE_REASONING_EFFORT": "turbo",
            },
            clear=True,
        ):
            settings = load_settings()

        self.assertEqual(settings.mode, "real")
        self.assertEqual(settings.reasoning_effort, "low")


if __name__ == "__main__":
    unittest.main()
