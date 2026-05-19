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


def test_parse_args_out_optional_defaults_none():
    ns = crawl.parse_args(["--categories", "cs.AI"])
    assert ns.out is None


def test_feed_date_from_pubdate(cs_ai_xml):
    from daily_arxiv_rss.parse import parse_feed
    assert crawl._feed_date(parse_feed(cs_ai_xml)) == "2026-05-18"


def test_feed_date_none_when_unparseable():
    from daily_arxiv_rss.parse import RawItem
    bad = [RawItem(guid="g", link="", title="", description="", pub_date="")]
    assert crawl._feed_date(bad) is None


def test_run_default_out_uses_feed_pubdate(tmp_path, monkeypatch, cs_ai_xml, cs_cl_xml):
    feeds_bytes = {"cs.AI": cs_ai_xml, "cs.CL": cs_cl_xml}
    monkeypatch.chdir(tmp_path)  # default path is relative: data/<date>.jsonl
    returned = crawl.run(categories=["cs.AI"], out_path=None,
                         sot_dir=str(tmp_path / "rss"), yyyymmdd="20260519",
                         fetcher=lambda c: feeds_bytes[c])
    expected = tmp_path / "data" / "2026-05-18.jsonl"  # feed pubDate, NOT 0519
    assert expected.exists()
    assert returned == "data/2026-05-18.jsonl"  # run() returns the path it wrote
    assert len(expected.read_text(encoding="utf-8").splitlines()) == 3


def test_main_prints_only_path_to_stdout(tmp_path, monkeypatch, capsys, cs_ai_xml, cs_cl_xml):
    fb = {"cs.AI": cs_ai_xml, "cs.CL": cs_cl_xml}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CATEGORIES", "cs.AI")
    monkeypatch.setattr(crawl, "_default_fetcher", lambda c: fb[c])
    crawl.main(["--sot-dir", str(tmp_path / "rss")])
    out = capsys.readouterr().out.strip()
    assert out == "data/2026-05-18.jsonl"  # stdout = just the path (scripts capture this)
