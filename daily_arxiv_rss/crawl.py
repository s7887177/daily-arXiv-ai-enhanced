import argparse
import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from daily_arxiv_rss import feeds
from daily_arxiv_rss.parse import parse_feed
from daily_arxiv_rss.transform import build_announce_index, assemble, write_jsonl


def _default_fetcher(category: str) -> bytes:
    return feeds.fetch(feeds.feed_url(category))


def _feed_date(items) -> str | None:
    """The announcement date written on the feed (RSS pubDate) as YYYY-MM-DD."""
    for it in items:
        if it.pub_date:
            try:
                return parsedate_to_datetime(it.pub_date).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                continue
    return None


def run(categories, out_path, sot_dir, yyyymmdd, fetcher=None):
    if fetcher is None:
        fetcher = _default_fetcher
    parsed: dict[str, list] = {}

    def pull(cat: str):
        if cat in parsed:
            return
        xml = fetcher(cat)
        feeds.save_sot(xml, feeds.sot_path(sot_dir, cat, yyyymmdd))
        parsed[cat] = parse_feed(xml)

    for cat in categories:
        pull(cat)

    requested = {c: parsed[c] for c in categories if c in parsed}

    if out_path is None:
        date = None
        for c in categories:
            if c in requested:
                date = _feed_date(requested[c])
                if date:
                    break
        if date is None:
            date = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
            print(f"[warn] no parseable feed pubDate; falling back to {date}",
                  file=sys.stderr)
        out_path = os.path.join("data", f"{date}.jsonl")

    extra: set[str] = set()
    for items in requested.values():
        for it in items:
            if it.announce_type == "cross":
                extra.update(it.categories)
    for cat in sorted(extra - set(parsed)):
        try:
            pull(cat)
        except Exception as e:  # primary-resolution feed is best-effort
            print(f"[warn] could not fetch feed {cat}: {e}", file=sys.stderr)

    announce_index = build_announce_index(parsed)
    records = assemble(requested, announce_index)
    write_jsonl(records, out_path)
    print(f"wrote {len(records)} records to {out_path}", file=sys.stderr)
    return out_path


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=None,
                   help="output JSONL path; default data/<feed pubDate>.jsonl")
    p.add_argument("--categories",
                   default=os.environ.get("CATEGORIES", "cs.CV"))
    p.add_argument("--sot-dir", default="data/rss")
    ns = p.parse_args(argv)
    ns.categories = [c.strip() for c in ns.categories.split(",") if c.strip()]
    return ns


def main(argv=None):
    ns = parse_args(argv)
    yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path = run(ns.categories, ns.out, ns.sot_dir, yyyymmdd)
    print(out_path)  # stdout = just the written path, for run.sh/run.yml to capture


if __name__ == "__main__":
    main()
