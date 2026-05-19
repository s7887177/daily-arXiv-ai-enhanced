from daily_arxiv_rss.parse import parse_feed


def test_parse_feed_extracts_items(cs_ai_xml):
    items = parse_feed(cs_ai_xml)
    assert len(items) == 3
    first = items[0]
    assert first.guid == "oai:arXiv.org:2605.15204v1"
    assert first.link == "https://arxiv.org/abs/2605.15204"
    assert first.title == "SDOF: Taming the Alignment Tax"
    assert first.announce_type == "new"
    assert first.categories == ["cs.AI"]
    assert first.dc_creator == "Zhantao Wang"
    assert "constrained state machine" in first.description


def test_parse_feed_multi_category_order_preserved(cs_ai_xml):
    items = parse_feed(cs_ai_xml)
    cross = items[2]
    assert cross.announce_type == "cross"
    assert cross.categories == ["cs.AI", "cs.CL", "cs.IR"]
