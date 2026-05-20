"""Background RSS poller — capture arXiv's RSS dynamics over weeks.

Polls a small set of arXiv categories at a fixed interval and stores every
fetch as an immutable SOT under ``experiments/rss-watch/snapshots/<cat>/``.
The point is empirical: by accumulating ~1k–10k snapshots we can answer
"how does arXiv's RSS actually behave?" — when does the channel pubDate roll,
how fast does a single pubDate window grow, are rolls synchronised across
unrelated categories?

Commands:
  daemon   loop forever, fetching every --interval seconds
  fetch    one-shot cycle (useful for cron or manual ping)
  status   print the current per-cat last-fetch summary
  stats    analyse every saved snapshot and print a digest
  stop     send SIGTERM to the running daemon

Defaults: cs.AI, astro-ph.CO, econ.EM | 30 min | experiments/rss-watch/
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from daily_arxiv_rss.feeds import feed_url, fetch
from daily_arxiv_rss.state import now_iso

DEFAULT_CATS = ["cs.AI", "astro-ph.CO", "econ.EM"]
DEFAULT_INTERVAL = 30 * 60
DEFAULT_ROOT = Path("experiments/rss-watch")


# ----------------------------- io helpers ---------------------------------

def _read_json(p: Path, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")


def _log(root: Path, line: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "daemon.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _parse_channel(xml_bytes: bytes) -> dict:
    rt = ET.fromstring(xml_bytes)
    ch = rt.find("channel")
    items = ch.findall("item")
    guids = []
    item_pubs = Counter()
    for it in items:
        g = (it.findtext("guid") or "").strip()
        if g:
            guids.append(g)
        ip = (it.findtext("pubDate") or "").strip()
        if ip:
            item_pubs[ip] += 1
    return {"channel_pubdate": (ch.findtext("pubDate") or "").strip(),
            "lastbuilddate": (ch.findtext("lastBuildDate") or "").strip(),
            "items": len(items),
            "guids": guids,
            "item_pubs": dict(item_pubs)}


# ----------------------------- fetch ---------------------------------------

def fetch_one(root: Path, cat: str, fetcher=None) -> dict:
    """Fetch ``cat`` once, save SOT, return summary dict (no exception leaks)."""
    if fetcher is None:
        fetcher = lambda c: fetch(feed_url(c))
    ts = now_iso()
    snap_dir = root / "snapshots" / cat
    snap_dir.mkdir(parents=True, exist_ok=True)
    try:
        xml_bytes = fetcher(cat)
        (snap_dir / f"{ts}.xml").write_bytes(xml_bytes)
        ch = _parse_channel(xml_bytes)
        return {"cat": cat, "fetched_at": ts, "ok": True,
                "channel_pubdate": ch["channel_pubdate"],
                "lastbuilddate": ch["lastbuilddate"],
                "items": ch["items"], "bytes": len(xml_bytes)}
    except Exception as e:                       # network / parse / disk
        return {"cat": cat, "fetched_at": ts, "ok": False,
                "err": f"{type(e).__name__}: {e}"}


def update_status(root: Path, results: list[dict]) -> dict:
    p = root / "status.json"
    s = _read_json(p, {})
    s.setdefault("started_at", now_iso())
    s["last_cycle_at"] = now_iso()
    s["total_cycles"] = s.get("total_cycles", 0) + 1
    per_cat = s.setdefault("per_cat", {})
    for r in results:
        cat = r["cat"]
        cs = per_cat.setdefault(cat, {"snapshots": 0, "fail": 0})
        if r["ok"]:
            cs["snapshots"] += 1
            cs["last_ok_at"] = r["fetched_at"]
            cs["last_channel_pubdate"] = r["channel_pubdate"]
            cs["last_lastbuilddate"] = r["lastbuilddate"]
            cs["last_items"] = r["items"]
            cs["last_bytes"] = r["bytes"]
        else:
            cs["fail"] += 1
            cs["last_err"] = r["err"]
            cs["last_err_at"] = r["fetched_at"]
    _write_json(p, s)
    return s


def fetch_cycle(root: Path, cats: list[str], fetcher=None) -> list[dict]:
    root.mkdir(parents=True, exist_ok=True)
    results = [fetch_one(root, c, fetcher=fetcher) for c in cats]
    update_status(root, results)
    for r in results:
        if r["ok"]:
            _log(root, f"{r['fetched_at']} {r['cat']:>14} ok    "
                       f"items={r['items']:5d}  "
                       f"channel_pubdate={r['channel_pubdate']}")
        else:
            _log(root, f"{r['fetched_at']} {r['cat']:>14} FAIL  {r['err']}")
    return results


# ----------------------------- daemon --------------------------------------

def _interruptible_sleep(seconds: int, stop_flag) -> None:
    slept = 0
    while slept < seconds and not stop_flag["stop"]:
        chunk = min(5, seconds - slept)
        time.sleep(chunk)
        slept += chunk


def daemon(root: Path, cats: list[str], interval_s: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    pid_file = root / "daemon.pid"
    if pid_file.exists():
        try:
            old = int(pid_file.read_text().strip())
            os.kill(old, 0)
            print(f"daemon already running (pid {old}); "
                  f"`stop` first or remove {pid_file}", file=sys.stderr)
            sys.exit(2)
        except (ProcessLookupError, ValueError):
            pid_file.unlink(missing_ok=True)
    pid_file.write_text(str(os.getpid()))

    stop_flag = {"stop": False}

    def _handler(signum, frame):
        stop_flag["stop"] = True

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
    _log(root, f"# daemon started pid={os.getpid()} cats={cats} "
               f"interval={interval_s}s")
    try:
        while not stop_flag["stop"]:
            try:
                fetch_cycle(root, cats)
            except Exception as e:               # cycle bug shouldn't kill us
                _log(root, f"# cycle error: {type(e).__name__}: {e}")
            _interruptible_sleep(interval_s, stop_flag)
    finally:
        pid_file.unlink(missing_ok=True)
        _log(root, "# daemon stopped")


def stop_daemon(root: Path) -> None:
    pid_file = root / "daemon.pid"
    if not pid_file.exists():
        print("no daemon.pid; nothing to stop", file=sys.stderr)
        sys.exit(1)
    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"sent SIGTERM to pid {pid}")
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        print(f"pid {pid} not running; removed stale pid file")


def status(root: Path) -> None:
    s = _read_json(root / "status.json", {})
    print(json.dumps(s, ensure_ascii=False, indent=2))


# ----------------------------- stats ---------------------------------------

def _parse_snapshot_file(p: Path) -> dict:
    info = _parse_channel(p.read_bytes())
    info["ts"] = p.stem
    return info


def compute_stats(root: Path) -> dict:
    """Pure-data analysis of saved snapshots; returns a dict for rendering."""
    snap_root = root / "snapshots"
    out = {"per_cat": {}, "cross_cat_roll_clusters": []}
    cat_rolls: dict[str, list] = {}
    if not snap_root.exists():
        return out
    for cat_dir in sorted(p for p in snap_root.iterdir() if p.is_dir()):
        cat = cat_dir.name
        snaps = sorted(cat_dir.glob("*.xml"))
        if not snaps:
            out["per_cat"][cat] = {"snapshots": 0}
            continue
        parsed = [_parse_snapshot_file(p) for p in snaps]

        # roll detection (channel pubDate changes)
        rolls = []
        prev_cp = None
        for s in parsed:
            cp = s["channel_pubdate"]
            if prev_cp is not None and cp != prev_cp:
                rolls.append({"ts": s["ts"], "from": prev_cp, "to": cp})
            prev_cp = cp
        cat_rolls[cat] = rolls

        # within-window growth + lifetimes
        by_window: dict[str, list] = defaultdict(list)
        for s in parsed:
            by_window[s["channel_pubdate"]].append(s)
        windows = []
        for cp, group in sorted(by_window.items()):
            ids_union: set[str] = set()
            for s in group:
                ids_union.update(s["guids"])
            windows.append({
                "channel_pubdate": cp,
                "snapshots": len(group),
                "first_ts": group[0]["ts"], "last_ts": group[-1]["ts"],
                "items_min": min(s["items"] for s in group),
                "items_max": max(s["items"] for s in group),
                "items_last": group[-1]["items"],
                "union_ids": len(ids_union),
            })

        # per-snapshot deltas (added/removed)
        deltas = []
        for i in range(1, len(parsed)):
            a = set(parsed[i - 1]["guids"])
            b = set(parsed[i]["guids"])
            deltas.append({"ts": parsed[i]["ts"],
                           "added": len(b - a), "removed": len(a - b)})
        if deltas:
            adds = [d["added"] for d in deltas]
            rems = [d["removed"] for d in deltas]
            delta_summary = {"max_add": max(adds), "mean_add": sum(adds) / len(adds),
                             "max_remove": max(rems),
                             "mean_remove": sum(rems) / len(rems),
                             "cycles": len(deltas)}
        else:
            delta_summary = None

        # id lifetimes (how many consecutive snapshots an id stays in feed)
        snap_count: dict[str, int] = defaultdict(int)
        first_seen: dict[str, str] = {}
        for s in parsed:
            for g in s["guids"]:
                first_seen.setdefault(g, s["ts"])
                snap_count[g] += 1
        latest_ids = set(parsed[-1]["guids"]) if parsed else set()
        rolled_out = sum(1 for g in first_seen if g not in latest_ids)
        avg_snaps_per_id = (sum(snap_count.values()) / len(snap_count)
                            if snap_count else 0)

        out["per_cat"][cat] = {
            "snapshots": len(parsed),
            "first_ts": parsed[0]["ts"], "last_ts": parsed[-1]["ts"],
            "rolls": rolls,
            "windows": windows,
            "delta": delta_summary,
            "unique_ids_seen": len(first_seen),
            "in_latest_snapshot": len(latest_ids),
            "rolled_out": rolled_out,
            "avg_snapshots_per_id": round(avg_snaps_per_id, 2),
        }

    # cross-cat roll alignment: cluster rolls happening within ~10 min
    all_rolls = [(cat, r["ts"], r["from"], r["to"])
                 for cat, rs in cat_rolls.items() for r in rs]
    all_rolls.sort(key=lambda x: x[1])
    clusters = []
    cur: list = []
    last_ts = None
    for cat, ts, fr, to in all_rolls:
        if last_ts is None or _ts_delta_minutes(last_ts, ts) <= 10:
            cur.append((cat, ts, fr, to))
        else:
            if len(cur) >= 2:
                clusters.append(cur)
            cur = [(cat, ts, fr, to)]
        last_ts = ts
    if len(cur) >= 2:
        clusters.append(cur)
    out["cross_cat_roll_clusters"] = [
        {"size": len(c),
         "members": [{"cat": x[0], "ts": x[1], "from": x[2], "to": x[3]}
                     for x in c]} for c in clusters]
    return out


def _ts_delta_minutes(a: str, b: str) -> float:
    # both in YYYYMMDDTHHMMSSZ
    from datetime import datetime
    fmt = "%Y%m%dT%H%M%SZ"
    da = datetime.strptime(a, fmt)
    db = datetime.strptime(b, fmt)
    return abs((db - da).total_seconds()) / 60.0


def render_stats(s: dict) -> str:
    lines: list[str] = []
    for cat, c in s["per_cat"].items():
        lines.append(f"\n=== {cat} ===")
        if c.get("snapshots", 0) == 0:
            lines.append("  (no snapshots)")
            continue
        lines.append(f"  snapshots         : {c['snapshots']}  "
                     f"({c['first_ts']} → {c['last_ts']})")
        lines.append(f"  channel pubDate rolls: {len(c['rolls'])}")
        for r in c["rolls"][:8]:
            lines.append(f"    {r['ts']}  {r['from']}  →  {r['to']}")
        if len(c["rolls"]) > 8:
            lines.append(f"    ... and {len(c['rolls']) - 8} more")
        lines.append(f"  windows observed  : {len(c['windows'])}")
        for w in c["windows"][-5:]:
            lines.append(
                f"    {w['channel_pubdate'][:25]:25s}  "
                f"snaps={w['snapshots']:3d}  "
                f"items {w['items_min']}-{w['items_max']} "
                f"(last={w['items_last']})  union={w['union_ids']}")
        d = c.get("delta")
        if d:
            lines.append(
                f"  per-cycle delta   : add max={d['max_add']} "
                f"mean={d['mean_add']:.1f}  | "
                f"remove max={d['max_remove']} mean={d['mean_remove']:.1f}  "
                f"({d['cycles']} cycles)")
        lines.append(f"  unique ids ever   : {c['unique_ids_seen']}")
        lines.append(f"  in latest snap    : {c['in_latest_snapshot']}")
        lines.append(f"  rolled out        : {c['rolled_out']}")
        lines.append(f"  avg snaps per id  : {c['avg_snapshots_per_id']}")
    clusters = s.get("cross_cat_roll_clusters") or []
    lines.append(f"\n=== cross-cat roll alignment "
                 f"(rolls within 10 min across cats) ===")
    if not clusters:
        lines.append("  (no synchronised rolls observed yet)")
    for c in clusters:
        lines.append(f"  cluster of {c['size']}:")
        for m in c["members"]:
            lines.append(f"    {m['ts']}  {m['cat']:>14}  "
                         f"{m['from']}  →  {m['to']}")
    return "\n".join(lines)


def stats(root: Path) -> None:
    print(render_stats(compute_stats(root)))


# ----------------------------- cli -----------------------------------------

def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="rss_watch")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--cats", default=",".join(DEFAULT_CATS),
                    help="comma-separated categories")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                    help="seconds between cycles (daemon only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("daemon", "fetch", "status", "stats", "stop"):
        sub.add_parser(c)
    return ap.parse_args(argv)


def main(argv=None):
    ns = parse_args(argv)
    root = Path(ns.root)
    cats = [c.strip() for c in ns.cats.split(",") if c.strip()]
    if ns.cmd == "daemon":
        daemon(root, cats, ns.interval)
    elif ns.cmd == "fetch":
        for r in fetch_cycle(root, cats):
            print(json.dumps(r, ensure_ascii=False))
    elif ns.cmd == "status":
        status(root)
    elif ns.cmd == "stats":
        stats(root)
    elif ns.cmd == "stop":
        stop_daemon(root)


if __name__ == "__main__":
    main()
