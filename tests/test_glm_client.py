import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BOT_DIR = Path(__file__).resolve().parents[1] / "feishu_bot"
sys.path.insert(0, str(BOT_DIR))

import glm_client  # noqa: E402


class _Response:
    status_code = 200

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


class GlmClientTests(unittest.TestCase):
    def test_web_search_tool_is_only_added_when_requested(self):
        with (
            patch.dict(os.environ, {"ZAI_API_KEY": "test-key"}),
            patch.object(glm_client.requests, "post", return_value=_Response()) as post,
        ):
            self.assertEqual(glm_client.call_glm("test", web_search=True), "ok")

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["tools"][0]["type"], "web_search")
        self.assertTrue(payload["tools"][0]["web_search"]["enable"])
        self.assertEqual(payload["tool_choice"], "auto")

    def test_plain_call_does_not_use_web_search(self):
        with (
            patch.dict(os.environ, {"ZAI_API_KEY": "test-key"}),
            patch.object(glm_client.requests, "post", return_value=_Response()) as post,
        ):
            glm_client.call_glm("test")

        self.assertNotIn("tools", post.call_args.kwargs["json"])


if __name__ == "__main__":
    unittest.main()
