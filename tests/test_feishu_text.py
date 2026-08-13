import sys
import unittest
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "feishu_bot"
sys.path.insert(0, str(BOT_DIR))

from feishu_text import format_latex_for_feishu  # noqa: E402


class FeishuTextTests(unittest.TestCase):
    def test_inline_superscript(self):
        self.assertEqual(format_latex_for_feishu("RL$^2$-VLA"), "RL²-VLA")

    def test_common_inline_formula(self):
        self.assertEqual(
            format_latex_for_feishu(r"use $x_1 \times x_2$ and $\alpha$"),
            "use x₁ × x₂ and α",
        )

    def test_block_formula_has_no_dollar_delimiters(self):
        result = format_latex_for_feishu("before $$x^2 + y^2$$ after")
        self.assertNotIn("$", result)
        self.assertIn("x² + y²", result)


if __name__ == "__main__":
    unittest.main()
