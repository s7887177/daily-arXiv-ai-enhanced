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


from daily_arxiv_rss.transform import build_announce_index, resolved_categories


def test_cross_primary_resolution(cs_ai_xml, cs_cl_xml):
    feeds = {"cs.AI": parse_feed(cs_ai_xml), "cs.CL": parse_feed(cs_cl_xml)}
    idx = build_announce_index(feeds)
    cross = parse_feed(cs_ai_xml)[2]  # 2605.15202v1, cross in cs.AI
    cats = resolved_categories(cross, idx)
    assert cats[0] == "cs.CL"  # cs.CL feed has it as 'new' -> primary
    assert set(cats) == {"cs.AI", "cs.CL", "cs.IR"}


def test_cross_primary_fallback_keeps_order(cs_ai_xml):
    feeds = {"cs.AI": parse_feed(cs_ai_xml)}  # cs.CL feed NOT available
    idx = build_announce_index(feeds)
    cross = parse_feed(cs_ai_xml)[2]
    cats = resolved_categories(cross, idx)
    assert cats == ["cs.AI", "cs.CL", "cs.IR"]  # unchanged fallback


def test_resolved_categories_noop_for_new_item(cs_ai_xml):
    feeds = {"cs.AI": parse_feed(cs_ai_xml)}
    idx = build_announce_index(feeds)
    new_item = parse_feed(cs_ai_xml)[1]
    assert resolved_categories(new_item, idx) == ["cs.AI", "cs.CE"]
