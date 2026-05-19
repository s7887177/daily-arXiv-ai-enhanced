import json

from daily_arxiv_rss import manifest


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_build_parses_sorts_and_preserves(tmp_path):
    date = "2026-05-19"
    # one crawled paper with a jsonl record
    _write(tmp_path / f"data/{date}.jsonl", json.dumps({
        "id": "2605.16775v1", "categories": ["cs.CV"],
        "abs": "https://arxiv.org/abs/2605.16775",
        "pdf": "https://arxiv.org/pdf/2605.16775",
        "authors": ["A. One", "B. Two"], "title": "Some Paper",
    }, ensure_ascii=False) + "\n")
    _write(tmp_path / "data/articles/2605.16775v1.md",
           "# 白話標題\n\n> 原始論文：Some Paper\n"
           "> 作者·單位：A. One、B. Two（某大學）\n"
           "> arXiv：2605.16775v1 ・ 分類：cs.CV\n\n"
           "一句話說重點：這是重點。\n\n---\n\n## 背景\n...\n")
    # an older article (lower id) to verify newest-first ordering
    _write(tmp_path / "data/articles/2605.15217v1.md",
           "# 舊文標題\n\n一句話說重點：舊重點。\n---\n")
    # a hand-written seed already in a prior manifest, NOT in today's jsonl
    _write(tmp_path / f"data/articles/{date}.json", json.dumps({
        "date": date, "articles": [{
            "id": "2605.15217v1", "arxiv_id": "2605.15217",
            "headline": "保留的手寫標題", "hook": "保留 hook",
            "category_label": "AI", "importance": "高",
            "authors": "Seed Author", "affiliations": "Seed Lab",
            "url": "u", "pdf": "p", "date": date,
            "md": "data/articles/2605.15217v1.md"}]}, ensure_ascii=False))

    summary = manifest.build(date, repo_root=str(tmp_path))
    assert summary["articles"] == 2
    assert summary["jsonl_matched"] == 1
    assert summary["preserved"] == 1

    out = json.loads((tmp_path / f"data/articles/{date}.json").read_text("utf-8"))
    arts = out["articles"]
    # newest arXiv id first
    assert [a["arxiv_id"] for a in arts] == ["2605.16775", "2605.15217"]
    a0 = arts[0]
    assert a0["headline"] == "白話標題"
    assert a0["hook"] == "這是重點。"
    assert a0["category_label"] == "cs.CV"
    assert a0["affiliations"] == "某大學"
    assert a0["authors"] == "A. One、B. Two"
    assert a0["md"] == "data/articles/2605.16775v1.md"
    # hand-written seed preserved verbatim
    seed = next(a for a in arts if a["id"] == "2605.15217v1")
    assert seed["headline"] == "保留的手寫標題"
    assert seed["importance"] == "高"

    idx = json.loads((tmp_path / "data/articles/index.json").read_text("utf-8"))
    assert idx["dates"] == [date]
