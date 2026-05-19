import json
from pathlib import Path
from daily_arxiv_rss import dedup


def _w(p: Path, ids):
    p.write_text("\n".join(json.dumps({"id": i, "title": i}) for i in ids) + "\n",
                 encoding="utf-8")


def test_no_history_is_all_new(tmp_path):
    f = tmp_path / "2026-05-18.jsonl"
    _w(f, ["2605.1v1", "2605.2v1"])
    assert dedup.dedupe(str(f)) == "has_new_content"
    assert len(f.read_text().splitlines()) == 2


def test_removes_papers_seen_in_prior_7_days(tmp_path):
    _w(tmp_path / "2026-05-17.jsonl", ["2605.1v1"])
    _w(tmp_path / "2026-05-12.jsonl", ["2605.9v1"])  # within 7d window
    today = tmp_path / "2026-05-18.jsonl"
    _w(today, ["2605.1v1", "2605.9v1", "2605.NEWv1"])
    assert dedup.dedupe(str(today)) == "has_new_content"
    ids = [json.loads(l)["id"] for l in today.read_text().splitlines()]
    assert ids == ["2605.NEWv1"]


def test_all_duplicate_deletes_file(tmp_path):
    _w(tmp_path / "2026-05-17.jsonl", ["2605.1v1"])
    today = tmp_path / "2026-05-18.jsonl"
    _w(today, ["2605.1v1"])
    assert dedup.dedupe(str(today)) == "no_new_content"
    assert not today.exists()


def test_versioned_id_v1_v2_not_duplicate(tmp_path):
    _w(tmp_path / "2026-05-17.jsonl", ["2605.5v1"])
    today = tmp_path / "2026-05-18.jsonl"
    _w(today, ["2605.5v2"])  # new version -> NOT a duplicate
    assert dedup.dedupe(str(today)) == "has_new_content"
    assert [json.loads(l)["id"] for l in today.read_text().splitlines()] == ["2605.5v2"]


def test_outside_7day_window_not_dedup(tmp_path):
    _w(tmp_path / "2026-05-10.jsonl", ["2605.1v1"])  # 8 days before 05-18
    today = tmp_path / "2026-05-18.jsonl"
    _w(today, ["2605.1v1"])
    assert dedup.dedupe(str(today)) == "has_new_content"


def test_missing_file_is_no_data(tmp_path):
    assert dedup.dedupe(str(tmp_path / "2026-05-18.jsonl")) == "no_data"


def test_empty_file_is_no_data(tmp_path):
    f = tmp_path / "2026-05-18.jsonl"
    f.write_text("", encoding="utf-8")
    assert dedup.dedupe(str(f)) == "no_data"


def test_status_to_exitcode_matches_check_stats_contract():
    assert dedup.exit_code("has_new_content") == 0
    assert dedup.exit_code("no_new_content") == 1
    assert dedup.exit_code("no_data") == 1
    assert dedup.exit_code("error") == 2
