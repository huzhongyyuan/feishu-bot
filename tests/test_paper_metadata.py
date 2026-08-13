import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BOT_DIR = Path(__file__).resolve().parents[1] / "feishu_bot"
sys.path.insert(0, str(BOT_DIR))

import paper_metadata  # noqa: E402


class PaperMetadataTests(unittest.TestCase):
    def test_extracts_numbered_affiliations_after_authors(self):
        text = """
Fast-WAM: Do World Action Models Need Test-time Future Imagination?
Tianyuan Yuan1,2, Zibin Dong1,2, Yicheng Liu1,2, Hang Zhao1,2
1IIIS, Tsinghua University
2Galaxea AI
Abstract
This paper studies world action models.
"""
        institutions = paper_metadata.extract_institutions_from_text(
            text,
            ["Tianyuan Yuan", "Zibin Dong", "Yicheng Liu", "Hang Zhao"],
        )
        self.assertEqual(
            institutions,
            ["IIIS, Tsinghua University", "Galaxea AI"],
        )

    def test_does_not_infer_institution_from_abstract(self):
        text = """
An Example Paper
Alice Smith, Bob Jones
Abstract
We evaluate the system at Stanford University.
"""
        self.assertEqual(
            paper_metadata.extract_institutions_from_text(
                text,
                ["Alice Smith", "Bob Jones"],
            ),
            [],
        )

    def test_extracts_inline_author_affiliations(self):
        text = """
        Motion Paper
        KAIFENG ZHAO, NVIDIA, Switzerland and ETH Zürich, Switzerland
        MATHIS PETROVICH, NVIDIA, Switzerland
        Abstract
        """
        self.assertEqual(
            paper_metadata.extract_institutions_from_text(
                text,
                ["Kaifeng Zhao", "Mathis Petrovich"],
            ),
            ["NVIDIA", "ETH Zürich"],
        )

    def test_extracts_numbered_original_contributions(self):
        text = """
        In summary, the key contributions of this paper are (1) a hybrid
        latent-body representation for controllable motion generation,
        (2) a two-stage autoregressive diffusion model, and (3) an extensive
        evaluation on a production-quality dataset.
        2 Related Work
        This content must not be included.
        """
        self.assertEqual(
            paper_metadata.extract_original_contributions_from_text(text),
            [
                "a hybrid latent-body representation for controllable motion generation",
                "a two-stage autoregressive diffusion model",
                "an extensive evaluation on a production-quality dataset.",
            ],
        )

    def test_extracts_bulleted_original_contributions(self):
        text = """
        Before delving into details, our core contributions are as,
        • We present the first training-free framework for general subjects.
        • We propose a simple module for injecting motion flows.
        2 Related Work
        """
        self.assertEqual(
            len(paper_metadata.extract_original_contributions_from_text(text)),
            2,
        )

    @patch.object(paper_metadata, "extract_pdf_metadata")
    def test_enrichment_uses_official_pdf_and_preserves_authors(self, extract):
        extract.return_value = {
            "institutions": ["Example University"],
            "contributions_original": ["We introduce a verified method."],
        }
        paper = {
            "id": "2603.16666",
            "title": "Verified",
            "authors": ["Alice Smith"],
        }
        result = paper_metadata.enrich_paper_metadata(paper)
        self.assertEqual(result["authors"], ["Alice Smith"])
        self.assertEqual(result["institutions"], ["Example University"])
        self.assertEqual(
            result["contributions_original"],
            ["We introduce a verified method."],
        )
        self.assertEqual(result["institutions_source"], "official_pdf_first_page")
        extract.assert_called_once_with(
            "https://arxiv.org/pdf/2603.16666",
            ["Alice Smith"],
        )


if __name__ == "__main__":
    unittest.main()
