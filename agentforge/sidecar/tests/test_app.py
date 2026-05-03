import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from agentforge_sidecar.app import app
from agentforge_sidecar.security import sign_payload
from agentforge_sidecar.settings import Settings


SECRET = "test-agentforge-signing-secret"


def _payload(expires_at: datetime | str | None = None) -> dict:
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    if isinstance(expires_at, datetime):
        expires_at = expires_at.isoformat()
    return {
        "schema_version": "agentforge.request.v1",
        "request_id": "req-test",
        "conversation_id": "conv-test",
        "expires_at": expires_at,
        "purpose": "patient_rounding_brief",
        "scope": {
            "user_hash": "user",
            "patient_hash": "patient",
            "encounter_hash": "encounter",
            "evidence_bundle_id": "bundle-test",
        },
        "message": "Give me a chart brief for rounds.",
        "evidence_bundle": {
            "id": "bundle-test",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "patient_context": {"patient_id": "123", "encounter_id": "456"},
            "sources": [
                {
                    "id": "problem-1",
                    "record_type": "problem",
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "field_path": "lists.title",
                    "value": "Pneumonia",
                }
            ],
            "adapter_status": [{"adapter": "problem_list", "status": "success"}],
        },
    }


def _post(client: TestClient, body: dict, secret: str = SECRET):
    return client.post("/v1/chat", json=body, headers={"X-AgentForge-Signature": sign_payload(body, secret)})


class AppRequestValidationTest(unittest.TestCase):
    def test_valid_signed_unexpired_request_succeeds(self):
        body = _payload()
        settings = Settings(mode="mock", signing_secret=SECRET, request_ttl_seconds=300)
        with patch("agentforge_sidecar.app.load_settings", return_value=settings):
            response = _post(TestClient(app), body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["verification_status"], "verified")

    def test_expired_request_is_rejected(self):
        body = _payload(datetime.now(timezone.utc) - timedelta(minutes=2))
        settings = Settings(mode="mock", signing_secret=SECRET, request_ttl_seconds=300)
        with patch("agentforge_sidecar.app.load_settings", return_value=settings):
            response = _post(TestClient(app), body)

        self.assertEqual(response.status_code, 401)
        self.assertIn("Expired", response.json()["detail"])

    def test_far_future_request_is_rejected(self):
        body = _payload(datetime.now(timezone.utc) + timedelta(minutes=20))
        settings = Settings(mode="mock", signing_secret=SECRET, request_ttl_seconds=300)
        with patch("agentforge_sidecar.app.load_settings", return_value=settings):
            response = _post(TestClient(app), body)

        self.assertEqual(response.status_code, 401)
        self.assertIn("expiration exceeds", response.json()["detail"])

    def test_invalid_timestamp_is_rejected(self):
        body = _payload("not-a-timestamp")
        settings = Settings(mode="mock", signing_secret=SECRET, request_ttl_seconds=300)
        with patch("agentforge_sidecar.app.load_settings", return_value=settings):
            response = _post(TestClient(app), body)

        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid", response.json()["detail"])

    def test_missing_signing_secret_fails_closed(self):
        body = _payload()
        settings = Settings(mode="mock", signing_secret="", request_ttl_seconds=300)
        with patch("agentforge_sidecar.app.load_settings", return_value=settings):
            response = _post(TestClient(app), body)

        self.assertEqual(response.status_code, 503)
        self.assertIn("signing secret", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
