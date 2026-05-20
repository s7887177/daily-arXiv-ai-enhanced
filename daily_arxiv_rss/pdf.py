"""State-driven PDF downloader.

Reads ``.state/rss/pdf-status.json`` (populated by ``crawl``) and downloads
PDFs to ``pdfs/<id>.pdf``. Status transitions per id:

  pending  → ok       (file downloaded, size > 0)
  pending  → failed   (download error; sets retry_after for cool-down)
  failed   → ok       (a later retry succeeds)
  ok       → ok       (skipped; file present and whole)
  ok       → pending  (file missing or 0-byte; will retry)

Honest semantics so consumers can tell "we tried and arXiv refuses" apart
from "we haven't tried yet".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from daily_arxiv_rss.state import State, now_iso


def _arxiv_downloader(arxiv_id: str, dest: str) -> None:
    """Default downloader (kept thin so tests can inject)."""
    import arxiv
    client = arxiv.Client()
    result = next(client.results(arxiv.Search(id_list=[arxiv_id])))
    d = Path(dest)
    result.download_pdf(dirpath=str(d.parent), filename=d.name)


def _iso_to_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _retry_after_iso(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)) \
        .strftime("%Y%m%dT%H%M%SZ")


def download_all(repo_root: str = ".", *,
                 downloader=_arxiv_downloader, sleep=time.sleep,
                 retries: int = 3, base_delay: float = 3.0,
                 retry_after_hours: float = 4.0,
                 max_ids: int | None = None) -> dict:
    st = State(repo_root)
    status = st.pdf_status()
    pdfs_dir = Path(repo_root) / "pdfs"
    pdfs_dir.mkdir(exist_ok=True)
    summary = {"ok": 0, "skipped_existing": 0, "skipped_cooldown": 0,
               "fetched_now": 0, "failed": 0}
    now = datetime.now(timezone.utc)

    eligible = []
    for arxiv_id, info in status.items():
        dest = pdfs_dir / f"{arxiv_id}.pdf"
        cur = info.get("status", "pending")

        # ok + file whole → skip; ok + file missing/0-byte → re-queue
        if cur == "ok":
            if dest.exists() and dest.stat().st_size > 0:
                summary["skipped_existing"] += 1
                continue
            info["status"] = "pending"            # was lost on disk
            cur = "pending"

        # failed and still in cool-down
        if cur == "failed":
            ra = info.get("retry_after")
            try:
                ra_dt = _iso_to_dt(ra) if ra else None
            except ValueError:
                ra_dt = None
            if ra_dt and now < ra_dt:
                summary["skipped_cooldown"] += 1
                continue

        eligible.append(arxiv_id)
        if max_ids is not None and len(eligible) >= max_ids:
            break

    for arxiv_id in eligible:
        info = status[arxiv_id]
        dest = pdfs_dir / f"{arxiv_id}.pdf"
        info["attempts"] = info.get("attempts", 0) + 1
        info["last_attempt"] = now_iso()
        ok = False
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                downloader(arxiv_id, str(dest))
                if dest.exists() and dest.stat().st_size > 0:
                    ok = True
                    break
                last_err = "0-byte response"
                if dest.exists():
                    dest.unlink()                  # cleanup corrupt file
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
            if attempt < retries:
                sleep(base_delay * (2 ** (attempt - 1)))
        if ok:
            info["status"] = "ok"
            info.pop("last_err", None)
            info.pop("retry_after", None)
            summary["ok"] += 1
            summary["fetched_now"] += 1
        else:
            info["status"] = "failed"
            info["last_err"] = last_err or "unknown"
            info["retry_after"] = _retry_after_iso(retry_after_hours)
            summary["failed"] += 1
            print(f"[warn] pdf failed {arxiv_id}: {last_err}",
                  file=sys.stderr)
        sleep(base_delay)

    st.write_pdf_status(status)
    st.journal({"kind": "pdf", "summary": summary,
                "eligible": len(eligible)})
    print(f"PDF summary: {summary}", file=sys.stderr)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--max-ids", type=int, default=None,
                    help="cap how many PDFs to fetch this run (test/throttle)")
    ap.add_argument("--retry-after-hours", type=float, default=4.0,
                    help="cool-down after failure")
    ns = ap.parse_args(argv)
    download_all(repo_root=ns.repo_root, max_ids=ns.max_ids,
                 retry_after_hours=ns.retry_after_hours)


if __name__ == "__main__":
    main()
