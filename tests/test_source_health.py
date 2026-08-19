import pytest

import source_health


def test_source_health_records_success_and_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(source_health, "DB_PATH", tmp_path / "health.db")
    assert source_health.track_source("arxiv", lambda: [1, 2]) == [1, 2]
    row = source_health.health_snapshot()[0]
    assert row["ok"] is True
    assert row["candidate_count"] == 2

    with pytest.raises(RuntimeError):
        source_health.track_source("arxiv", lambda: [], require_nonempty=True)
    row = source_health.health_snapshot()[0]
    assert row["ok"] is False
    assert row["consecutive_failures"] == 1
