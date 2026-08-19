from datetime import datetime, timedelta, timezone

import paper_candidate_pool


def test_candidate_pool_persists_and_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_candidate_pool, "DB_PATH", tmp_path / "pool.db")
    paper = {
        "id": "2608.12345",
        "title": "Persistent Candidate",
        "source": "arXiv",
        "published": datetime.now(timezone.utc).isoformat(),
    }
    assert paper_candidate_pool.store_candidates([paper]) == 1
    assert paper_candidate_pool.eligible_candidates()[0]["title"] == paper["title"]

    paper_candidate_pool.mark_candidates([paper], "deferred", "temporary limit")
    assert paper_candidate_pool.eligible_candidates() == []

    with paper_candidate_pool._connect() as conn:
        conn.execute(
            "UPDATE candidates SET next_retry_at=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),),
        )
    assert paper_candidate_pool.eligible_candidates()[0]["title"] == paper["title"]


def test_candidate_pool_merges_richer_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_candidate_pool, "DB_PATH", tmp_path / "pool.db")
    paper_candidate_pool.store_candidates([{"id": "2608.1", "title": "P", "source": "arXiv"}])
    paper_candidate_pool.store_candidates(
        [{"id": "2608.1", "title": "P", "source": "HF", "code_url": "https://github.com/o/r"}]
    )
    assert paper_candidate_pool.eligible_candidates()[0]["code_url"] == "https://github.com/o/r"
