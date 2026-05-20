import json

from daily_arxiv_rss import writer


def test_merge_jsonl_append_only_by_id(tmp_path):
    p = tmp_path / "2026-05-19.jsonl"
    added, total = writer.merge_jsonl(p, [
        {"id": "a", "title": "A"}, {"id": "b", "title": "B"}])
    assert (added, total) == (2, 2)

    # second merge: "b" already exists with original record, "c" is new
    added, total = writer.merge_jsonl(p, [
        {"id": "b", "title": "B-CHANGED"}, {"id": "c", "title": "C"}])
    assert (added, total) == (1, 3)

    recs = {json.loads(l)["id"]: json.loads(l)
            for l in p.read_text("utf-8").splitlines() if l.strip()}
    assert recs["b"]["title"] == "B"                  # original preserved


def test_group_by_pub_date_splits():
    recs = [
        {"id": "1", "pub_date": "2026-05-19"},
        {"id": "2", "pub_date": "2026-05-19"},
        {"id": "3", "pub_date": "2026-05-20"},
        {"id": "4", "pub_date": ""},                  # dropped
    ]
    g = writer.group_by_pub_date(recs)
    assert sorted(g) == ["2026-05-19", "2026-05-20"]
    assert {r["id"] for r in g["2026-05-19"]} == {"1", "2"}


def test_merge_by_pub_date_writes_separate_files(tmp_path):
    recs = [
        {"id": "a", "pub_date": "2026-05-19", "title": "A"},
        {"id": "b", "pub_date": "2026-05-20", "title": "B"},
    ]
    summary = writer.merge_by_pub_date(recs, data_dir=str(tmp_path))
    assert summary["2026-05-19"]["added"] == 1
    assert summary["2026-05-20"]["added"] == 1
    assert (tmp_path / "2026-05-19.jsonl").exists()
    assert (tmp_path / "2026-05-20.jsonl").exists()
