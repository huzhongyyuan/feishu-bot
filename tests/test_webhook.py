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
        self.env_patch = patch.dict(
            os.environ,
            {
                "FEISHU_VERIFICATION_TOKEN": "",
                "FEISHU_ALLOWED_OPEN_IDS": "",
                "FEISHU_ALLOWED_CHAT_IDS": "",
                "FEISHU_BOT_OPEN_ID": "ou_bot",
            },
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = TestClient(main.app)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_paper_pipeline_health(self):
        with (
            patch("source_health.health_snapshot", return_value=[]),
            patch("paper_candidate_pool.pool_summary", return_value={"pending": 2}),
        ):
            response = self.client.get("/health/papers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["candidate_pool"], {"pending": 2})

    def test_yuanbao_keyword_routes_from_any_position(self):
        self.assertTrue(main._is_yuanbao_request("请让元宝总结一下"))
        self.assertTrue(main._is_yuanbao_request("今天的新闻，交给元宝"))
        self.assertFalse(main._is_yuanbao_request("请普通总结一下"))

    def test_chatgpt_keyword_and_command_cleanup(self):
        self.assertTrue(main._is_chatgpt_request("问 GPT 这个问题"))
        self.assertTrue(main._is_chatgpt_request("请交给ChatGPT"))
        self.assertFalse(main._is_chatgpt_request("请普通总结一下"))
        self.assertEqual(main._strip_chatgpt_command("问GPT 测试"), "测试")
        self.assertEqual(main._strip_chatgpt_command("GPT：测试"), "测试")

    def test_yuanbao_takes_precedence_over_chatgpt(self):
        with (
            patch.object(main, "call_glm"),
            patch.dict(os.environ, {"CHAT_PROVIDER": "auto"}),
            patch("yuanbao_agent.ask_yuanbao", return_value="元宝回答"),
        ):
            result = main._chat_answer("元宝比较一下 GPT")

        self.assertIn("【元宝", result)
        self.assertIn("元宝回答", result)

    def test_chatgpt_request_uses_web_agent(self):
        with patch("chatgpt_agent.ask_chatgpt", return_value="网页回答"):
            result = main._chat_answer("问GPT 测试")

        self.assertEqual(result, "【ChatGPT 网页】\n\n网页回答")

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
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "id": {"open_id": "ou_bot"},
                            "name": "HumanGroupBot",
                        }
                    ],
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

    def test_subscription_command_skips_general_chat(self):
        with (
            patch.object(
                main,
                "handle_subscription_command",
                return_value="订阅已更新",
            ),
            patch.object(main, "send_text_message") as send_text,
            patch.object(main, "classify_intent") as classify_intent,
        ):
            main.process_message("oc_test", "查看订阅")

        send_text.assert_called_once_with("oc_test", "订阅已更新")
        classify_intent.assert_not_called()

    def test_verified_metadata_overrides_model_claims(self):
        paper = {
            "id": "2607.12345",
            "title": "Verified Title",
            "authors": ["Author A"],
            "abstract": "Official abstract",
            "paper_url": "https://arxiv.org/abs/2607.12345",
        }
        model_output = {
            "title": "Invented Title",
            "authors": ["Fake Author"],
            "abstract": "Fake abstract",
            "paper_url": "https://example.com/fake",
            "code_url": "https://example.com/fake-code",
            "summary": "AI interpretation",
        }

        result = main._merge_verified_paper_data(paper, model_output)

        self.assertEqual(result["title"], "Verified Title")
        self.assertEqual(result["authors"], ["Author A"])
        self.assertEqual(result["abstract"], "Official abstract")
        self.assertEqual(result["paper_url"], "https://arxiv.org/abs/2607.12345")
        self.assertEqual(result["code_url"], "")
        self.assertEqual(result["summary"], "AI interpretation")

    def test_manual_paper_card_contains_bilingual_guide_and_abstract(self):
        with patch.object(main, "_send_feishu_message") as send:
            main.send_card(
                "oc_test",
                {
                    "title": "Paper",
                    "summary": "中文导读。",
                    "summary_en": "English guide.",
                    "abstract_zh": "中文摘要翻译。",
                    "abstract": "Official abstract.",
                    "paper_url": "https://arxiv.org/abs/2608.00001",
                    "contributions": [],
                    "code_url": "https://github.com/org/paper",
                    "llm_open_source_verified": True,
                    "open_source_verified": True,
                    "large_team_verified": True,
                },
            )
        card = send.call_args.args[2]
        content = str(card["elements"])
        self.assertIn("开源代码", content)
        self.assertIn("https://github.com/org/paper", content)
        self.assertIn("中文导读", content)
        self.assertIn("English Guide", content)
        self.assertIn("摘要 · 中文翻译", content)
        self.assertIn("Abstract · English Original", content)
        self.assertIn(
            "🏷 [arXiv](https://arxiv.org/abs/2608.00001)",
            content,
        )

    def test_non_allowlisted_sender_is_ignored(self):
        payload = {
            "header": {
                "event_id": f"blocked-{time.time_ns()}",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"open_id": "ou_other"},
                },
                "message": {
                    "chat_id": "oc_test",
                    "message_type": "text",
                    "create_time": str(int(time.time() * 1000)),
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "id": {"open_id": "ou_bot"},
                            "name": "HumanGroupBot",
                        }
                    ],
                    "content": json.dumps(
                        {"text": "@_user_1 问 GPT 测试"},
                        ensure_ascii=False,
                    ),
                },
            },
        }

        with (
            patch.dict(
                os.environ,
                {"FEISHU_ALLOWED_OPEN_IDS": "ou_huu"},
            ),
            patch.object(main, "process_message") as process_message,
        ):
            response = self.client.post("/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        process_message.assert_not_called()

    def test_group_allowlist_permits_members_only_in_that_chat(self):
        payload = {
            "header": {
                "event_id": f"group-allowed-{time.time_ns()}",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"open_id": "ou_group_member"},
                },
                "message": {
                    "chat_id": "oc_shared_group",
                    "message_type": "text",
                    "create_time": str(int(time.time() * 1000)),
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "id": {"open_id": "ou_bot"},
                            "name": "HumanGroupBot",
                        }
                    ],
                    "content": json.dumps(
                        {"text": "@_user_1 问 GPT 测试"},
                        ensure_ascii=False,
                    ),
                },
            },
        }
        with (
            patch.dict(
                os.environ,
                {
                    "FEISHU_ALLOWED_OPEN_IDS": "ou_huu",
                    "FEISHU_ALLOWED_CHAT_IDS": "oc_shared_group",
                },
            ),
            patch.object(main, "process_message") as process_message,
        ):
            response = self.client.post("/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        process_message.assert_called_once_with("oc_shared_group", "问 GPT 测试")

    def test_mentioning_another_user_does_not_trigger_bot(self):
        payload = {
            "header": {
                "event_id": f"other-mention-{time.time_ns()}",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"open_id": "ou_huu"},
                },
                "message": {
                    "chat_id": "oc_shared_group",
                    "message_type": "text",
                    "create_time": str(int(time.time() * 1000)),
                    "mentions": [
                        {
                            "key": "@_user_1",
                            "id": {"open_id": "ou_someone_else"},
                            "name": "其他用户",
                        }
                    ],
                    "content": json.dumps(
                        {"text": "@_user_1 你看一下"},
                        ensure_ascii=False,
                    ),
                },
            },
        }
        with patch.object(main, "process_message") as process_message:
            response = self.client.post("/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        process_message.assert_not_called()

    def test_private_chat_does_not_require_bot_mention(self):
        payload = {
            "header": {
                "event_id": f"private-{time.time_ns()}",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"open_id": "ou_huu"},
                },
                "message": {
                    "chat_id": "oc_private_huu",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "create_time": str(int(time.time() * 1000)),
                    "mentions": [],
                    "content": json.dumps(
                        {"text": "推荐一篇具身智能论文"},
                        ensure_ascii=False,
                    ),
                },
            },
        }
        with (
            patch.dict(
                os.environ,
                {"FEISHU_ALLOWED_OPEN_IDS": "ou_huu,ou_wang"},
            ),
            patch.object(main, "process_message") as process_message,
        ):
            response = self.client.post("/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        process_message.assert_called_once_with(
            "oc_private_huu", "推荐一篇具身智能论文"
        )

    def test_private_chat_rejects_group_only_collaborator(self):
        payload = {
            "header": {
                "event_id": f"private-blocked-{time.time_ns()}",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"open_id": "ou_wang"},
                },
                "message": {
                    "chat_id": "oc_private_wang",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "create_time": str(int(time.time() * 1000)),
                    "mentions": [],
                    "content": json.dumps({"text": "你好"}, ensure_ascii=False),
                },
            },
        }
        with (
            patch.dict(
                os.environ,
                {
                    "FEISHU_ALLOWED_OPEN_IDS": "ou_huu,ou_wang",
                    "FEISHU_ALLOWED_CHAT_IDS": "oc_private_wang",
                },
            ),
            patch.object(main, "process_message") as process_message,
        ):
            response = self.client.post("/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        process_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
