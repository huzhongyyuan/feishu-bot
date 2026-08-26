import daily_paper


def _paper(title, **values):
    return {"title": title, "paper_url": f"https://papers.test/{title}", **values}


def test_official_fallback_only_keeps_verified_untried_undelivered():
    conference = _paper("Conference Paper", conference_verified=True)
    journal = _paper("Journal Paper", journal_verified=True)
    plain = _paper("Plain arXiv Paper")
    delivered = _paper("Already Sent", journal_verified=True)

    result = daily_paper._official_venue_fallback_candidates(
        [conference, journal, plain, delivered],
        attempted_identities={daily_paper._candidate_identity(conference)},
        delivered_titles={"already sent"},
    )

    assert result == [journal]


def test_verify_candidate_batches_continues_until_official_paper_passes():
    candidates = [
        _paper("Rejected 1", conference_verified=True),
        _paper("Rejected 2", journal_verified=True),
        _paper("Accepted", journal_verified=True, code_url="https://github.com/a/b"),
        _paper("Not Attempted", conference_verified=True),
    ]
    calls = []

    def verifier(batch):
        calls.append([paper["title"] for paper in batch])
        return [paper for paper in batch if paper.get("code_url")]

    verified, attempted = daily_paper._verify_candidate_batches(
        candidates,
        verifier,
        batch_size=2,
        target_count=1,
    )

    assert [paper["title"] for paper in verified] == ["Accepted"]
    assert [paper["title"] for paper in attempted] == [
        "Rejected 1",
        "Rejected 2",
        "Accepted",
        "Not Attempted",
    ]
    assert calls == [["Rejected 1", "Rejected 2"], ["Accepted", "Not Attempted"]]


def test_verify_candidate_batches_does_not_accept_unverified_code():
    candidates = [_paper("No Open Source", conference_verified=True)]

    verified, attempted = daily_paper._verify_candidate_batches(
        candidates,
        lambda batch: [],
    )

    assert verified == []
    assert attempted == candidates
