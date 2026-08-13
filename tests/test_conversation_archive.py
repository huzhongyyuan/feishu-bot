import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch


BOT_DIR = Path(__file__).resolve().parents[1] / "feishu_bot"
sys.path.insert(0, str(BOT_DIR))

import conversation_archive  # noqa: E402


class ConversationArchiveTests(unittest.TestCase):
    def test_title_matching_tolerates_punctuation_only(self):
        self.assertTrue(
            conversation_archive._title_matches(
                "MUGEN: A Unified Framework",
                "MUGEN - A Unified Framework",
            )
        )
        self.assertFalse(
            conversation_archive._title_matches(
                "MUGEN: A Unified Framework",
                "A Different Paper About Motion",
            )
        )

    def test_arxiv_links_are_verified_and_deduplicated(self):
        paper = {"id": "2607.29633", "title": "OASIS"}
        with (
            patch.object(
                conversation_archive,
                "_query_arxiv",
                return_value=[paper],
            ) as query,
            patch.object(
                conversation_archive,
                "_extract_explicit_titles",
                return_value=[],
            ),
        ):
            result = conversation_archive._find_verified_papers(
                "看 https://arxiv.org/abs/2607.29633v1",
                "PDF https://arxiv.org/pdf/2607.29633",
            )
        self.assertEqual(result, [paper])
        self.assertEqual(query.call_args_list[0], call({"id_list": "2607.29633"}))

    def test_papers_are_saved_before_feishu_archive(self):
        paper = {"id": "2607.29633", "title": "OASIS"}
        events = []
        with (
            patch.object(conversation_archive, "_already_archived", return_value=False),
            patch.object(
                conversation_archive,
                "_enrich_for_archive",
                return_value=[paper],
            ),
            patch.object(
                conversation_archive,
                "save_paper",
                side_effect=lambda _: events.append("save"),
            ),
            patch.object(
                conversation_archive,
                "archive_papers",
                side_effect=lambda _: events.append("archive"),
            ),
        ):
            count = conversation_archive.archive_conversation_papers([paper])
        self.assertEqual(count, 1)
        self.assertEqual(events, ["save", "archive"])


if __name__ == "__main__":
    unittest.main()
