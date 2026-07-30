import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BOT_DIR = Path(__file__).resolve().parents[1] / "feishu_bot"
sys.path.insert(0, str(BOT_DIR))

from chatgpt_agent import format_chatgpt_answer  # noqa: E402


class ChatGPTFormatTests(unittest.TestCase):
    def test_compacts_noise_blank_lines_and_table(self):
        answer = """
最近主要方向


方向\t最近动作\t背后目标
Codex Agent\t持续更新体验\t完成复杂工程任务
ChatGPT Agent\t融合工作流\t统一任务入口

X (formerly Twitter)
+1

1. 第一条趋势

说明内容

AI IDE List
"""
        result = format_chatgpt_answer(answer)

        self.assertNotIn("X (formerly Twitter)", result)
        self.assertNotIn("+1", result)
        self.assertNotIn("AI IDE List", result)
        self.assertIn("1. Codex Agent", result)
        self.assertIn("最近动作：持续更新体验", result)
        self.assertNotIn("\n\n\n", result)

    def test_cleans_tracking_links_and_deduplicates(self):
        result = format_chatgpt_answer(
            "参考内容",
            [
                "https://example.com/a?utm_source=chatgpt.com",
                "https://example.com/a",
            ],
        )

        self.assertIn("参考链接\nhttps://example.com/a", result)
        self.assertNotIn("utm_source", result)
        self.assertEqual(result.count("https://example.com/a"), 1)

    def test_limits_long_answers(self):
        with patch.dict(os.environ, {"CHATGPT_MAX_ANSWER_CHARS": "1000"}):
            result = format_chatgpt_answer("测试" * 1000)

        self.assertLessEqual(len(result), 1000)
        self.assertTrue(result.endswith("[内容已截断]"))


if __name__ == "__main__":
    unittest.main()
