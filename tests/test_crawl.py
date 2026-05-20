import json
from pathlib import Path

from daily_arxiv_rss import crawl


def test_crawl_writes_per_pubdate_jsonl(tmp_path, cs_ai_xml, cs_cl_xml):
    feeds_bytes = {"cs.AI": cs_ai_xml, "cs.CL": cs_cl_xml}
    fetched = []

    def fetcher(cat):
        fetched.append(cat)
        return feeds_bytes[cat]

    res = crawl.crawl(["cs.AI"], repo_root=str(tmp_path), fetcher=fetcher)
    # fixture items all have pubDate -> 2026-05-18
    pubdate_file = tmp_path / "data" / "2026-05-18.jsonl"
    assert pubdate_file.exists()
    recs = [json.loads(l) for l in pubdate_file.read_text("utf-8").splitlines()]
    assert len(recs) == 3
    assert {r["pub_date"] for r in recs} == {"2026-05-18"}
    assert res["status"] == "ok"
    assert res["records"] == 3
    assert res["by_pub_date"]["2026-05-18"]["added"] == 3
    # cross-resolution still picks cs.CL as primary for the cross item
    cross = [r for r in recs if r["id"] == "2605.15202v1"][0]
    assert cross["categories"][0] == "cs.CL"


def test_crawl_no_op_on_identical_guid_set(tmp_path, cs_ai_xml):
    feeds_bytes = {"cs.AI": cs_ai_xml}

    def fetcher(cat):
        return feeds_bytes[cat]

    crawl.crawl(["cs.AI"], repo_root=str(tmp_path), fetcher=fetcher)
    res2 = crawl.crawl(["cs.AI"], repo_root=str(tmp_path), fetcher=fetcher)
    assert res2["status"] == "no_op"
    journal = (tmp_path / ".state/rss/journal.jsonl").read_text("utf-8")
    assert journal.count('"status": "ok"') == 1
    assert journal.count('"status": "no_op"') == 1


def test_crawl_append_only_by_id(tmp_path, cs_ai_xml):
    """Second crawl with overlapping ids must NOT duplicate records."""
    feeds_bytes = {"cs.AI": cs_ai_xml}

    def fetcher(cat):
        return feeds_bytes[cat]

    crawl.crawl(["cs.AI"], repo_root=str(tmp_path), fetcher=fetcher)
    # force a non-no_op second run by clobbering the hash
    (tmp_path / ".state/rss/last-fetch.json").write_text(
        '{"cs.AI": {"guid_hash": "stale", "fetched_at": "", "items": 0}}',
        encoding="utf-8")
    res2 = crawl.crawl(["cs.AI"], repo_root=str(tmp_path), fetcher=fetcher)
    assert res2["status"] == "ok"
    assert res2["by_pub_date"]["2026-05-18"]["added"] == 0   # nothing new
    recs = (tmp_path / "data/2026-05-18.jsonl").read_text("utf-8").splitlines()
    assert len(recs) == 3                                    # not duplicated


def test_crawl_saves_versioned_sot(tmp_path, cs_ai_xml, cs_cl_xml):
    feeds_bytes = {"cs.AI": cs_ai_xml, "cs.CL": cs_cl_xml}
    crawl.crawl(["cs.AI"], repo_root=str(tmp_path),
                fetcher=lambda c: feeds_bytes[c])
    sots = sorted((tmp_path / "data/rss").glob("*.xml"))
    assert {p.name.split("_")[0] for p in sots} >= {"cs.AI", "cs.CL"}
    for p in sots:
        ts = p.stem.split("_", 1)[1]
        assert len(ts) == 16 and ts.endswith("Z")            # ISO basic UTC


def test_crawl_does_not_touch_pdf_state(tmp_path, cs_ai_xml):
    """crawl never writes into pdf-failures.json — that file is owned by
    the pdf module. The pdf module discovers wanted ids from jsonl, not
    from a queue we'd write here."""
    crawl.crawl(["cs.AI"], repo_root=str(tmp_path),
                fetcher=lambda c: cs_ai_xml)
    pf = tmp_path / ".state/rss/pdf-failures.json"
    assert not pf.exists()
