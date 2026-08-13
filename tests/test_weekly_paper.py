import sys
from datetime import datetime
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1] / "feishu_bot"
sys.path.insert(0, str(BOT_DIR))

import weekly_paper  # noqa: E402


def _paper(identity: str, title: str, abstract: str) -> dict:
    return {
        "id": identity,
        "title": title,
        "abstract": abstract,
        "published": "2026-08-02T00:00:00+00:00",
    }


def test_weekly_category_scores_are_specific():
    motion = _paper("m1", "Text-to-Motion Synthesis", "human animation")
    world = _paper("w1", "A World Model for Agents", "latent dynamics")
    assert weekly_paper.weekly_category_score(motion, "motion_generation") > 0
    assert weekly_paper.weekly_category_score(motion, "world_models") == 0
    assert weekly_paper.weekly_category_score(world, "world_models") > 0


def test_category_allocation_is_unique_and_three_per_group():
    preferred_start = datetime(2026, 7, 27, tzinfo=weekly_paper.SHANGHAI)
    papers = []
    for index in range(3):
        papers.extend(
            [
                _paper(f"m{index}", f"Motion Generation {index}", "text-to-motion"),
                _paper(f"v{index}", f"Video Generation {index}", "video diffusion"),
                _paper(f"e{index}", f"Embodied AI {index}", "robot manipulation"),
                _paper(f"w{index}", f"World Model {index}", "latent dynamics"),
            ]
        )
    allocation = weekly_paper.allocate_weekly_categories(
        papers,
        preferred_start,
        per_category=3,
    )
    assert all(len(allocation[key]) == 3 for key in weekly_paper.WEEKLY_CATEGORY_ORDER)
    identities = [paper["id"] for values in allocation.values() for paper in values]
    assert len(identities) == len(set(identities)) == 12
