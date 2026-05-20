"""Probe → early-exit-on-no-change → full crawl → per-pubDate JSONL merge.

This is the entry point of the RSS module. Its **promise** to consumers:

  After successful invocation:
    - ``data/<pub_date>.jsonl`` only grows (append-only-by-id).
    - ``data/rss/<cat>_<fetched-at>.xml`` is the immutable SOT (never overwritten).
    - New ids are queued in ``.state/rss/pdf-status.json`` as ``pending``.
    - One ``.state/rss/journal.jsonl`` line records what happened.
    - On no-op (probe sees no GUID-set change), exit 1, no artifacts change.

Exit codes:
  0 = work done (new ids merged into one or more per-pubDate jsonls)
  1 = no-op (probe identical to last-fetch; nothing fetched beyond probe)
  2 = error
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from daily_arxiv_rss import feeds, state as state_mod, writer
from daily_arxiv_rss.parse import parse_feed
from daily_arxiv_rss.transform import (assemble, build_announce_index)


def _default_fetcher(category: str) -> bytes:
    return feeds.fetch(feeds.feed_url(category))


def crawl(categories, repo_root: str = ".", fetcher=None) -> dict:
    if fetcher is None:
        fetcher = _default_fetcher
    if not categories:
        raise ValueError("no categories")
    st = state_mod.State(repo_root)
    probe_cat = categories[0]

    # 1. probe (cheap): always fetch the first category and hash its GUID set
    probe_xml = fetcher(probe_cat)
    probe_items = parse_feed(probe_xml)
    h = state_mod.guid_hash(it.guid for it in probe_items)
    fetched_at = state_mod.now_iso()
    last = st.last_fetch(probe_cat)

    # 2. early-exit: identical GUID set since last run → no work
    if last and last.get("guid_hash") == h:
        st.journal({"kind": "crawl", "status": "no_op", "probe": probe_cat,
                    "items": len(probe_items)})
        return {"status": "no_op", "probe": probe_cat,
                "items": len(probe_items)}

    # 3. probe shows change → save it and fetch the rest
    st.save_sot(probe_cat, probe_xml, fetched_at)
    parsed: dict[str, list] = {probe_cat: probe_items}
    for cat in categories[1:]:
        try:
            xml = fetcher(cat)
        except Exception as e:                # one bad cat shouldn't kill all
            print(f"[warn] fetch failed {cat}: {e}", file=sys.stderr)
            continue
        st.save_sot(cat, xml, fetched_at)
        parsed[cat] = parse_feed(xml)

    # 4. supplementary cross-resolution feeds (best-effort)
    extra: set[str] = set()
    for items in parsed.values():
        for it in items:
            if it.announce_type == "cross":
                extra.update(it.categories)
    for cat in sorted(extra - set(parsed)):
        try:
            xml = fetcher(cat)
        except Exception as e:
            print(f"[warn] cross-feed fetch failed {cat}: {e}", file=sys.stderr)
            continue
        st.save_sot(cat, xml, fetched_at)
        parsed[cat] = parse_feed(xml)

    # 5. assemble records (existing transform logic; now tags pub_date)
    requested = {c: parsed[c] for c in categories if c in parsed}
    idx = build_announce_index(parsed)
    records = assemble(requested, idx)

    # 6. merge into per-pubDate jsonls (append-only-by-id).
    #    NB: the pdf module owns the "what to fetch" decision and reads
    #    these jsonls directly; we do NOT write into pdf-failures here.
    merge_summary = writer.merge_by_pub_date(
        records, data_dir=str(os.path.join(repo_root, "data")))

    # 7. record last-fetch + journal
    st.set_last_fetch(probe_cat, fetched_at, h, len(probe_items))
    st.journal({"kind": "crawl", "status": "ok", "fetched_at": fetched_at,
                "categories": sorted(parsed),
                "by_pub_date": merge_summary,
                "records": len(records)})

    return {"status": "ok", "fetched_at": fetched_at,
            "categories": sorted(parsed), "records": len(records),
            "by_pub_date": merge_summary}


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--categories",
                   default=os.environ.get("CATEGORIES", "cs.CV"))
    p.add_argument("--repo-root", default=".")
    ns = p.parse_args(argv)
    ns.categories = [c.strip() for c in ns.categories.split(",") if c.strip()]
    return ns


def main(argv=None):
    ns = parse_args(argv)
    res = crawl(ns.categories, repo_root=ns.repo_root)
    print(json.dumps(res, ensure_ascii=False))
    if res["status"] == "no_op":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
