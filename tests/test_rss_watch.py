import json

from daily_arxiv_rss import rss_watch


def _xml(channel_pub: str, lastbuild: str, item_guids,
         item_title_suffix: str = ""):
    """Build a minimal RSS document. ``item_title_suffix`` lets a test
    produce two snapshots with the SAME guids but different per-item
    content (catches the "item_updated" code path)."""
    items = "\n".join(
        f"<item><guid>oai:arXiv.org:{g}</guid>"
        f"<title>Paper {g}{item_title_suffix}</title>"
        f"<description>Abstract for {g}</description>"
        f"<pubDate>{channel_pub}</pubDate></item>"
        for g in item_guids)
    return (f'<rss version="2.0"><channel>'
            f"<pubDate>{channel_pub}</pubDate>"
            f"<lastBuildDate>{lastbuild}</lastBuildDate>"
            f"{items}</channel></rss>").encode("utf-8")


def test_fetch_one_writes_snapshot_and_returns_summary(tmp_path):
    x = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 04:00:00 +0000", ["1v1", "2v1", "3v1"])
    res = rss_watch.fetch_one(tmp_path, "cs.AI", fetcher=lambda c: x)
    assert res["ok"] is True
    assert res["items"] == 3
    assert res["channel_pubdate"] == "Tue, 19 May 2026 00:00:00 -0400"
    snaps = list((tmp_path / "snapshots/cs.AI").glob("*.xml"))
    assert len(snaps) == 1
    assert snaps[0].read_bytes() == x


def test_fetch_cycle_handles_per_cat_failure(tmp_path):
    x = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 04:00:00 +0000", ["a"])

    def fetcher(c):
        if c == "broken":
            raise RuntimeError("nope")
        return x

    rss_watch.fetch_cycle(tmp_path, ["cs.AI", "broken"], fetcher=fetcher)
    s = json.loads((tmp_path / "status.json").read_text("utf-8"))
    assert s["total_cycles"] == 1
    assert s["per_cat"]["cs.AI"]["snapshots"] == 1
    assert s["per_cat"]["broken"]["fail"] == 1
    assert "last_err" in s["per_cat"]["broken"]


def _make_snaps(tmp_path, cat, snaps):
    """Write a list of (ts, xml_bytes) into a category's snapshot dir."""
    d = tmp_path / "snapshots" / cat
    d.mkdir(parents=True)
    for ts, xml in snaps:
        (d / f"{ts}.xml").write_bytes(xml)


def test_classify_pubdate_roll(tmp_path):
    A = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 04:00:00 +0000", ["a"])
    B = _xml("Wed, 20 May 2026 00:00:00 -0400",
             "Wed, 20 May 2026 04:00:00 +0000", ["b"])
    _make_snaps(tmp_path, "cs.AI",
                [("20260519T120000Z", A), ("20260520T040001Z", B)])
    s = rss_watch.compute_stats(tmp_path)
    ev = s["per_cat"]["cs.AI"]["events"]
    assert len(ev) == 1 and ev[0]["kind"] == "pubdate_roll"
    assert ev[0]["channel_pubdate_changed"] is True


def test_classify_turnover_when_pubdate_same_but_guids_churn(tmp_path):
    """The 5/19→today bug: SAME channel pubDate but content totally rolled.
    Must be flagged (kind='turnover', lastbuilddate_changed=True)."""
    A = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 04:00:00 +0000",
             [f"a{i}v1" for i in range(10)])
    B = _xml("Tue, 19 May 2026 00:00:00 -0400",       # ← same pubDate
             "Wed, 20 May 2026 02:05:00 +0000",       # ← advanced
             [f"b{i}v1" for i in range(20)])          # ← completely different guids
    _make_snaps(tmp_path, "cs.AI",
                [("20260519T120000Z", A), ("20260520T020500Z", B)])
    s = rss_watch.compute_stats(tmp_path)
    c = s["per_cat"]["cs.AI"]
    assert c["event_kinds"]["turnover"] == 1
    ev = c["events"][0]
    assert ev["kind"] == "turnover"
    assert ev["channel_pubdate_changed"] is False
    assert ev["lastbuilddate_changed"] is True
    assert ev["guid_added"] == 20
    assert ev["guid_removed"] == 10


def test_classify_metadata_only_when_only_lastbuilddate_moves(tmp_path):
    """Bytes differ but no item-set change AND no per-item content change."""
    guids = ["x", "y"]
    A = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 04:00:00 +0000", guids)
    B = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 05:00:00 +0000", guids)
    _make_snaps(tmp_path, "cs.AI",
                [("20260519T120000Z", A), ("20260519T130000Z", B)])
    s = rss_watch.compute_stats(tmp_path)
    c = s["per_cat"]["cs.AI"]
    assert c["event_kinds"]["metadata_only"] == 1


def test_classify_identical_drops_event(tmp_path):
    """Truly identical bytes → no event in the list (but counted in event_kinds)."""
    X = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 04:00:00 +0000", ["a"])
    _make_snaps(tmp_path, "cs.AI",
                [("20260519T120000Z", X), ("20260519T125000Z", X)])
    s = rss_watch.compute_stats(tmp_path)
    c = s["per_cat"]["cs.AI"]
    assert c["event_kinds"].get("identical") == 1
    assert c["events"] == []


def test_classify_incremental(tmp_path):
    A = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 04:00:00 +0000",
             [f"a{i}v1" for i in range(10)])
    B = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 05:00:00 +0000",
             [f"a{i}v1" for i in range(11)])  # +1, no removal → ~9% churn
    _make_snaps(tmp_path, "cs.AI",
                [("20260519T120000Z", A), ("20260519T130000Z", B)])
    s = rss_watch.compute_stats(tmp_path)
    assert s["per_cat"]["cs.AI"]["event_kinds"]["incremental"] == 1


def test_item_updated_detected_when_content_changes_same_guid(tmp_path):
    """Same guids, different titles → item_updated count > 0."""
    A = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 04:00:00 +0000", ["x", "y"])
    B = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 05:00:00 +0000", ["x", "y"],
             item_title_suffix=" (revised)")
    _make_snaps(tmp_path, "cs.AI",
                [("20260519T120000Z", A), ("20260519T130000Z", B)])
    s = rss_watch.compute_stats(tmp_path)
    ev = s["per_cat"]["cs.AI"]["events"][0]
    assert ev["item_updated"] == 2
    # not pure metadata anymore because items changed
    assert ev["kind"] in ("incremental", "turnover")


def test_cross_cat_pubdate_roll_clusters(tmp_path):
    A19 = _xml("Tue, 19 May 2026 00:00:00 -0400",
               "Tue, 19 May 2026 04:00:00 +0000", ["x"])
    B20 = _xml("Wed, 20 May 2026 00:00:00 -0400",
               "Wed, 20 May 2026 04:00:01 +0000", ["y"])
    _make_snaps(tmp_path, "cs.AI",
                [("20260519T120000Z", A19), ("20260520T040001Z", B20)])
    _make_snaps(tmp_path, "astro-ph.CO",
                [("20260519T120100Z", A19),
                 ("20260520T040014Z",
                  _xml("Wed, 20 May 2026 00:00:00 -0400",
                       "Wed, 20 May 2026 04:00:14 +0000", ["z"]))])
    s = rss_watch.compute_stats(tmp_path)
    assert len(s["cross_cat_roll_clusters"]) == 1
    members = s["cross_cat_roll_clusters"][0]["members"]
    assert {m["cat"] for m in members} == {"cs.AI", "astro-ph.CO"}


def test_render_stats_emits_text(tmp_path):
    _make_snaps(tmp_path, "cs.AI",
                [("20260519T120000Z",
                  _xml("Tue, 19 May 2026 00:00:00 -0400",
                       "Tue, 19 May 2026 04:00:00 +0000", ["a"]))])
    txt = rss_watch.render_stats(rss_watch.compute_stats(tmp_path))
    assert "cs.AI" in txt and "snapshots" in txt
