"""One-shot pipeline snapshot — call this any time to know where we stand.

Used by ``/daily-digest`` as its state-aware entry: read this once, decide
whether to crawl, whether to start a pdf daemon, whether to dispatch article
agents, or whether there's truly nothing left to do.

Output (JSON on stdout):

  {
    "wanted":           N,   # ids the crawler has put into data/*.jsonl
    "have_pdfs":        M,   # of those, how many have a whole PDF on disk
    "have_articles":    K,   # of those, how many have data/articles/<id>.md
    "need_pdfs":        P,   # = wanted - have_pdfs
    "need_articles":    Q,   # = wanted - have_articles
    "pdfs_in_cooldown": C,   # ids in pdf-failures still inside retry_after
    "pdf_daemon_alive": bool,
    "pdf_daemon_pid":   int | null,
    "decision":         "all_done" | "write_articles" | "start_pdf"
                        | "wait_for_pdfs" | "crawl_then_recheck"
  }
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from daily_arxiv_rss.pdf import on_disk_ids, wanted_ids, _iso_to_dt
from daily_arxiv_rss.state import State


def snapshot(repo_root: str = ".") -> dict:
    st = State(repo_root)
    root = Path(repo_root)

    wanted = wanted_ids(repo_root)
    have = on_disk_ids(repo_root)
    arts = {p.stem for p in (root / "data" / "articles").glob("*.md")}

    failures = st.pdf_failures()
    now = datetime.now(timezone.utc)
    in_cooldown = 0
    for arxiv_id in wanted - have:
        f = failures.get(arxiv_id)
        if not f:
            continue
        ra = f.get("retry_after")
        try:
            ra_dt = _iso_to_dt(ra) if ra else None
        except ValueError:
            ra_dt = None
        if ra_dt and now < ra_dt:
            in_cooldown += 1

    pid = st.pdf_daemon_pid()
    alive = pid is not None

    need_pdfs = len(wanted - have)
    need_articles = len(wanted - arts)
    pdfs_fetchable_now = need_pdfs - in_cooldown    # not in cool-down

    # Decision tree (mirrors SKILL.md):
    if need_articles == 0:
        decision = "all_done"
    elif need_pdfs == 0:
        # every wanted id has a PDF; pure article phase
        decision = "write_articles"
    elif pdfs_fetchable_now > 0 and not alive:
        decision = "start_pdf"
    elif alive:
        decision = "wait_for_pdfs"
    else:
        # need_articles > 0, need_pdfs > 0, no daemon, nothing fetchable
        # (all remaining PDFs are in cooldown). Write what we can; the
        # cooldown ones become "unobtainable" until later.
        decision = "write_articles" if (len(wanted & have) - len(arts & have)) > 0 \
            else "wait_for_pdfs"

    return {
        "wanted": len(wanted),
        "have_pdfs": len(wanted & have),
        "have_articles": len(wanted & arts),
        "need_pdfs": need_pdfs,
        "need_articles": need_articles,
        "pdfs_in_cooldown": in_cooldown,
        "pdf_daemon_alive": alive,
        "pdf_daemon_pid": pid,
        "decision": decision,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ns = ap.parse_args(argv)
    print(json.dumps(snapshot(ns.repo_root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
