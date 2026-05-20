import json

from daily_arxiv_rss import manifest


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_groups_articles_by_record_pub_date(tmp_path):
    """Each article should be filed under its OWN paper's pub_date (from jsonl)."""
    # one paper on 5/19, one on 5/20 (per-pubDate jsonl files)
    _write(tmp_path / "data/2026-05-19.jsonl", json.dumps({
        "id": "2605.16775v1", "categories": ["cs.CV"],
        "abs": "https://arxiv.org/abs/2605.16775",
        "pdf": "https://arxiv.org/pdf/2605.16775",
        "authors": ["A. One", "B. Two"], "title": "Some Paper",
        "pub_date": "2026-05-19",
    }, ensure_ascii=False) + "\n")
    _write(tmp_path / "data/2026-05-20.jsonl", json.dumps({
        "id": "2605.99999v1", "categories": ["cs.AI"],
        "abs": "", "pdf": "", "authors": ["C. Three"], "title": "Next-Day",
        "pub_date": "2026-05-20",
    }, ensure_ascii=False) + "\n")
    _write(tmp_path / "data/articles/2605.16775v1.md",
           "# 白話標題\n\n> 原始論文：Some Paper\n"
           "> 作者·單位：A. One、B. Two（某大學）\n"
           "> arXiv：2605.16775v1 ・ 分類：cs.CV\n\n"
           "一句話說重點：這是重點。\n---\n## 背景\n...\n")
    _write(tmp_path / "data/articles/2605.99999v1.md",
           "# 隔天的標題\n\n一句話說重點：隔天重點。\n---\n")

    s = manifest.build(str(tmp_path))
    assert s["articles"] == 2
    assert s["dates"] == 2
    assert s["by_date"] == {"2026-05-19": 1, "2026-05-20": 1}

    # 5/19 manifest contains the 5/19 paper only
    m19 = json.loads((tmp_path / "data/articles/2026-05-19.json")
                     .read_text("utf-8"))
    assert [a["id"] for a in m19["articles"]] == ["2605.16775v1"]
    assert m19["articles"][0]["headline"] == "白話標題"
    assert m19["articles"][0]["affiliations"] == "某大學"
    # 5/20 manifest contains the 5/20 paper only
    m20 = json.loads((tmp_path / "data/articles/2026-05-20.json")
                     .read_text("utf-8"))
    assert [a["id"] for a in m20["articles"]] == ["2605.99999v1"]
    # index lists both dates, newest first
    idx = json.loads((tmp_path / "data/articles/index.json")
                     .read_text("utf-8"))
    assert idx["dates"] == ["2026-05-20", "2026-05-19"]


def test_preserves_hand_written_seeds_without_jsonl(tmp_path):
    """An md with no jsonl record but already present in an existing manifest
    keeps its hand-written entry verbatim."""
    _write(tmp_path / "data/articles/2605.15217v1.md",
           "# 種子文\n\n一句話說重點：種子重點。\n---\n")
    _write(tmp_path / "data/articles/2026-05-19.json", json.dumps({
        "date": "2026-05-19", "articles": [{
            "id": "2605.15217v1", "arxiv_id": "2605.15217",
            "headline": "保留的手寫標題", "hook": "保留 hook",
            "category_label": "AI", "importance": "高",
            "authors": "Seed Author", "affiliations": "Seed Lab",
            "url": "u", "pdf": "p", "date": "2026-05-19",
            "md": "data/articles/2605.15217v1.md"}]}, ensure_ascii=False))

    manifest.build(str(tmp_path))
    out = json.loads((tmp_path / "data/articles/2026-05-19.json")
                     .read_text("utf-8"))
    assert out["articles"][0]["headline"] == "保留的手寫標題"   # not re-parsed
    assert out["articles"][0]["importance"] == "高"


def test_falls_back_to_jsonl_filename_when_record_lacks_pub_date(tmp_path):
    """Back-compat: legacy jsonl record without pub_date field uses filename."""
    _write(tmp_path / "data/2026-05-19.jsonl", json.dumps({
        "id": "2605.1v1", "categories": ["cs.CV"],
        "abs": "", "pdf": "", "authors": ["X"], "title": "T"
        # NO pub_date field
    }) + "\n")
    _write(tmp_path / "data/articles/2605.1v1.md",
           "# T\n\n一句話說重點：r.\n---\n")
    s = manifest.build(str(tmp_path))
    assert s["by_date"] == {"2026-05-19": 1}


def test_removes_stale_manifest_for_emptied_date(tmp_path):
    """If a previously-published date now has 0 articles, its manifest is removed."""
    _write(tmp_path / "data/articles/2026-05-19.json", json.dumps({
        "date": "2026-05-19", "articles": []}, ensure_ascii=False))
    # no .md files at all → build → 5/19 manifest should be deleted
    manifest.build(str(tmp_path))
    assert not (tmp_path / "data/articles/2026-05-19.json").exists()
    idx = json.loads((tmp_path / "data/articles/index.json")
                     .read_text("utf-8"))
    assert idx["dates"] == []
