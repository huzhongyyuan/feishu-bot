import unittest

from yuanbao_agent import (
    _append_reference_links,
    _answer_prompt,
    _env_enabled,
    _format_answer,
    _new_reference_links,
)


class YuanbaoFormatTests(unittest.TestCase):
    def test_joins_standalone_bullets_and_spaces_sections(self):
        source = """开场
一、模型与开源
•
第一条
•
第二条
二、大厂动态
内容"""

        self.assertEqual(
            _format_answer(source),
            "开场\n\n一、模型与开源\n\n"
            "• 第一条\n• 第二条\n\n"
            "二、大厂动态\n\n内容",
        )

    def test_joins_standalone_number_markers(self):
        self.assertEqual(
            _format_answer("1.\n第一项\n2.\n第二项"),
            "1. 第一项\n2. 第二项",
        )

    def test_keeps_only_new_unique_http_links(self):
        links = _new_reference_links(
            {"https://yuanbao.tencent.com/"},
            [
                {"text": "元宝", "href": "https://yuanbao.tencent.com/"},
                {"text": "报告", "href": "https://example.com/report"},
                {"text": "重复", "href": "https://example.com/report"},
                {"text": "无效", "href": "javascript:void(0)"},
            ],
        )

        self.assertEqual(
            links,
            [{"text": "报告", "href": "https://example.com/report"}],
        )

    def test_appends_visible_urls_for_feishu(self):
        answer = _append_reference_links(
            "回答",
            [{"text": "技术报告", "href": "https://example.com/paper"}],
        )

        self.assertIn("参考链接", answer)
        self.assertIn("1. 技术报告\n   https://example.com/paper", answer)

    def test_boolean_environment_parser(self):
        self.assertTrue(_env_enabled("MISSING_TEST_VALUE", default=True))
        self.assertFalse(_env_enabled("MISSING_TEST_VALUE", default=False))

    def test_prompt_requires_plain_reference_urls(self):
        prompt = _answer_prompt("介绍一下")

        self.assertTrue(prompt.startswith("介绍一下"))
        self.assertIn("https://", prompt)
        self.assertIn("不要输出思考过程", prompt)


if __name__ == "__main__":
    unittest.main()
