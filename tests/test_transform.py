from daily_arxiv_rss.parse import parse_feed
from daily_arxiv_rss.transform import to_record


def test_to_record_maps_all_eight_fields(cs_ai_xml):
    items = parse_feed(cs_ai_xml)
    rec = to_record(items[1])  # 2605.15218v1, two categories
    assert set(rec.keys()) == {"id", "categories", "pdf", "abs",
                               "authors", "title", "comment", "summary"}
    assert rec["id"] == "2605.15218v1"
    assert rec["abs"] == "https://arxiv.org/abs/2605.15218"
    assert rec["pdf"] == "https://arxiv.org/pdf/2605.15218"
    assert rec["title"] == "CAX-Agent: A Lightweight Agent Harness"
    assert rec["authors"] == ["Chenying Lin", "Yichen Hai", "Yi He"]
    assert rec["categories"] == ["cs.AI", "cs.CE"]
    assert rec["comment"] is None
    assert rec["summary"].startswith("Large language models deployed")
    assert "Announce Type" not in rec["summary"]


def test_to_record_strips_oai_prefix_keeps_version(cs_ai_xml):
    rec = to_record(parse_feed(cs_ai_xml)[0])
    assert rec["id"] == "2605.15204v1"  # versioned, no oai: prefix
