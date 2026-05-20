import json
import time
from pathlib import Path

from daily_arxiv_rss import rss_watch


def _xml(channel_pub: str, lastbuild: str, item_guids):
    items = "\n".join(
        f"<item><guid>oai:arXiv.org:{g}</guid>"
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


def test_stats_detects_roll_and_within_window_growth(tmp_path):
    # Two snapshots in window-A (343 → 900 items, simulating growth),
    # then a roll to window-B with 460 items.
    snap_dir = tmp_path / "snapshots/cs.AI"
    snap_dir.mkdir(parents=True)
    A = _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 04:00:00 +0000",
             [f"a{i}v1" for i in range(5)])
    A2 = _xml("Tue, 19 May 2026 00:00:00 -0400",
              "Tue, 19 May 2026 23:00:00 +0000",
              [f"a{i}v1" for i in range(3, 12)])    # 6 overlap with A, 3 new
    B = _xml("Wed, 20 May 2026 00:00:00 -0400",
             "Wed, 20 May 2026 04:00:00 +0000",
             [f"b{i}v1" for i in range(7)])
    (snap_dir / "20260519T120000Z.xml").write_bytes(A)
    (snap_dir / "20260519T230000Z.xml").write_bytes(A2)
    (snap_dir / "20260520T040500Z.xml").write_bytes(B)

    s = rss_watch.compute_stats(tmp_path)
    c = s["per_cat"]["cs.AI"]
    assert c["snapshots"] == 3
    assert len(c["rolls"]) == 1
    assert c["rolls"][0]["from"] == "Tue, 19 May 2026 00:00:00 -0400"
    assert c["rolls"][0]["to"] == "Wed, 20 May 2026 00:00:00 -0400"
    assert c["rolls"][0]["ts"] == "20260520T040500Z"
    # two windows: A (2 snapshots) + B (1 snapshot)
    assert len(c["windows"]) == 2
    a_win = [w for w in c["windows"]
             if w["channel_pubdate"].startswith("Tue, 19")][0]
    assert a_win["snapshots"] == 2
    assert a_win["items_min"] == 5 and a_win["items_max"] == 9
    assert a_win["union_ids"] == 12             # 5 + 7 with 0 overlap by guid → wait
    # actually our guids include the oai prefix; both A and A2 share 2 guids (a3,a4),
    # so union should be 5 + 9 - 2 = 12
    # delta from A → A2: added 7, removed 3 (we keep a3,a4; lose a0,a1,a2)
    assert c["delta"]["max_add"] >= 7


def test_stats_cross_cat_roll_alignment(tmp_path):
    snap_root = tmp_path / "snapshots"
    for cat in ("cs.AI", "astro-ph.CO"):
        d = snap_root / cat
        d.mkdir(parents=True)
        # day-1 then day-2 snapshots, roll close in time across cats
        (d / "20260519T120000Z.xml").write_bytes(
            _xml("Tue, 19 May 2026 00:00:00 -0400",
                 "Tue, 19 May 2026 04:00:00 +0000", ["x"]))
    # cs.AI rolls at 04:00:01, astro-ph.CO at 04:00:14 (within 10 min)
    (snap_root / "cs.AI/20260520T040001Z.xml").write_bytes(
        _xml("Wed, 20 May 2026 00:00:00 -0400",
             "Wed, 20 May 2026 04:00:01 +0000", ["y"]))
    (snap_root / "astro-ph.CO/20260520T040014Z.xml").write_bytes(
        _xml("Wed, 20 May 2026 00:00:00 -0400",
             "Wed, 20 May 2026 04:00:14 +0000", ["z"]))
    s = rss_watch.compute_stats(tmp_path)
    assert len(s["cross_cat_roll_clusters"]) == 1
    members = s["cross_cat_roll_clusters"][0]["members"]
    assert {m["cat"] for m in members} == {"cs.AI", "astro-ph.CO"}


def test_render_stats_emits_text(tmp_path):
    snap_dir = tmp_path / "snapshots/cs.AI"
    snap_dir.mkdir(parents=True)
    (snap_dir / "20260519T120000Z.xml").write_bytes(
        _xml("Tue, 19 May 2026 00:00:00 -0400",
             "Tue, 19 May 2026 04:00:00 +0000", ["a"]))
    txt = rss_watch.render_stats(rss_watch.compute_stats(tmp_path))
    assert "cs.AI" in txt and "snapshots" in txt
