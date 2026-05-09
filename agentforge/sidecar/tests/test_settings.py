import os
import unittest
from unittest.mock import patch

from agentforge_sidecar.settings import load_settings


class SettingsTest(unittest.TestCase):
    def test_real_mode_uses_gpt_5_nano_low_reasoning_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings()

        self.assertEqual(settings.mode, "real")
        self.assertEqual(settings.model, "gpt-5-nano")
        self.assertEqual(settings.reasoning_effort, "low")
        self.assertEqual(settings.reasoning, {"effort": "low"})

    def test_model_and_reasoning_can_be_overridden(self):
        with patch.dict(
            os.environ,
            {
                "AGENTFORGE_OPENAI_MODEL": "gpt-5-nano",
                "AGENTFORGE_COMPOSE_MODEL": "gpt-5-nano",
                "AGENTFORGE_VERIFY_MODEL": "gpt-5-nano",
                "AGENTFORGE_REASONING_EFFORT": "medium",
                "AGENTFORGE_SOURCE_SELECTION_MODE": "deterministic",
                "AGENTFORGE_VERIFY_MODE": "deterministic",
                "AGENTFORGE_FAST_MODEL_PROVIDER": "none",
                "AGENTFORGE_RESPONSE_CACHE_ENABLED": "true",
                "AGENTFORGE_RESPONSE_CACHE_TTL_SECONDS": "90",
            },
            clear=True,
        ):
            settings = load_settings()

        self.assertEqual(settings.model, "gpt-5-nano")
        self.assertEqual(settings.compose_model, "gpt-5-nano")
        self.assertEqual(settings.verify_model, "gpt-5-nano")
        self.assertEqual(settings.reasoning_effort, "medium")
        self.assertEqual(settings.reasoning, {"effort": "medium"})
        self.assertEqual(settings.source_selection_mode, "deterministic")
        self.assertEqual(settings.verify_mode, "deterministic")
        self.assertEqual(settings.fast_model_provider, "none")
        self.assertTrue(settings.response_cache_enabled)
        self.assertEqual(settings.response_cache_ttl_seconds, 90)

    def test_invalid_mode_and_reasoning_fail_to_live_defaults(self):
        with patch.dict(
            os.environ,
            {
                "AGENTFORGE_MODE": "surprise",
                "AGENTFORGE_REASONING_EFFORT": "turbo",
                "AGENTFORGE_SOURCE_SELECTION_MODE": "chaos",
                "AGENTFORGE_VERIFY_MODE": "maybe",
                "AGENTFORGE_FAST_MODEL_PROVIDER": "llama-party",
            },
            clear=True,
        ):
            settings = load_settings()

        self.assertEqual(settings.mode, "real")
        self.assertEqual(settings.reasoning_effort, "low")
        self.assertEqual(settings.source_selection_mode, "auto")
        self.assertEqual(settings.verify_mode, "auto")
        self.assertEqual(settings.fast_model_provider, "none")


if __name__ == "__main__":
    unittest.main()
