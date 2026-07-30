import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


BOT_DIR = Path(__file__).resolve().parents[1] / "feishu_bot"
sys.path.insert(0, str(BOT_DIR))

import main  # noqa: E402


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_url_verification(self):
        response = self.client.post(
            "/webhook",
            json={"type": "url_verification", "challenge": "ok"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"challenge": "ok"})

    def test_verification_token_rejects_invalid_request(self):
        with patch.dict(os.environ, {"FEISHU_VERIFICATION_TOKEN": "secret"}):
            response = self.client.post(
                "/webhook",
                json={
                    "type": "url_verification",
                    "challenge": "ok",
                    "token": "wrong",
                },
            )
        self.assertEqual(response.status_code, 403)

    def test_message_is_dispatched_to_background_task(self):
        payload = {
            "header": {
                "event_id": f"test-{time.time_ns()}",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {"sender_type": "user"},
                "message": {
                    "chat_id": "oc_test",
                    "message_type": "text",
                    "create_time": str(int(time.time() * 1000)),
                    "mentions": [{"key": "@_user_1"}],
                    "content": json.dumps(
                        {"text": "@_user_1 问元宝 测试"},
                        ensure_ascii=False,
                    ),
                },
            },
        }

        with patch.object(main, "process_message") as process_message:
            response = self.client.post("/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"code": 0})
        process_message.assert_called_once_with("oc_test", "问元宝 测试")


if __name__ == "__main__":
    unittest.main()
