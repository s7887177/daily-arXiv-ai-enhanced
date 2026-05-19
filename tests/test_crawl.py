import json
from daily_arxiv_rss import crawl


def test_run_endtoend_with_injected_fetcher(tmp_path, cs_ai_xml, cs_cl_xml):
    feeds_bytes = {"cs.AI": cs_ai_xml, "cs.CL": cs_cl_xml}
    fetched = []

    def fetcher(category):
        fetched.append(category)
        return feeds_bytes[category]

    out = tmp_path / "2026-05-18.jsonl"
    crawl.run(categories=["cs.AI"], out_path=str(out),
              sot_dir=str(tmp_path / "rss"), yyyymmdd="20260518",
              fetcher=fetcher)
    assert "cs.AI" in fetched and "cs.CL" in fetched
    assert (tmp_path / "rss" / "cs.AI_20260518.xml").exists()
    assert (tmp_path / "rss" / "cs.CL_20260518.xml").exists()
    recs = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 3
    cross = [r for r in recs if r["id"] == "2605.15202v1"][0]
    assert cross["categories"][0] == "cs.CL"


def test_parse_args_defaults(monkeypatch):
    monkeypatch.setenv("CATEGORIES", "cs.AI, cs.CL")
    ns = crawl.parse_args(["--out", "data/x.jsonl"])
    assert ns.out == "data/x.jsonl"
    assert ns.categories == ["cs.AI", "cs.CL"]
    assert ns.sot_dir == "data/rss"
