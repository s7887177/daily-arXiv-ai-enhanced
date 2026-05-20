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
import email.utils
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from daily_arxiv_rss.state import State, now_iso

# arxiv's PDF endpoint accepts either bare id (2605.18801) or versioned
# (2605.18801v1). The versioned form returns that specific version.
# /pdf is explicitly Allow'd by arxiv.org/robots.txt for User-agent *.
_PDF_URL = "https://arxiv.org/pdf/{id}"
_UA = "daily-arxiv-rss/0.1 (educational use; contact via repo)"
_HTTP_TIMEOUT = 60
# arxiv.org/robots.txt sets `Crawl-delay: 15` for User-agent *. Honor it.
POLITE_DELAY_S = 15.0


class RateLimited(Exception):
    """Raised by the downloader on 429/503. Carries the server's Retry-After
    (seconds from now) when present."""
    def __init__(self, code: int, retry_after_seconds: float | None):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.retry_after_seconds = retry_after_seconds


def _parse_retry_after(value: str | None) -> float | None:
    """Parse RFC 7231 Retry-After (integer seconds OR HTTP-date)."""
    if not value:
        return None
    value = value.strip()
    try:
        return float(int(value))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())


def _arxiv_downloader(arxiv_id: str, dest: str) -> None:
    """Default downloader: direct HTTP GET to arxiv.org/pdf/<id>.

    We deliberately do NOT go through the `arxiv` Python library — its
    Search(id_list=...) metadata lookup hits export.arxiv.org/api/query
    (which arxiv.org/robots.txt Disallows for User-agent *) and frequently
    hangs 30s+. We already have the id, no metadata fetch needed.

    On 429/503 raises ``RateLimited`` (with Retry-After when given) so the
    caller can respect the server's cool-down rather than guessing.
    """
    url = _PDF_URL.format(id=arxiv_id)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (429, 503):
            ra = _parse_retry_after(e.headers.get("Retry-After")) \
                if e.headers else None
            raise RateLimited(e.code, ra) from e
        raise
    with open(dest, "wb") as f:
        f.write(data)


def _iso_to_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _retry_after_iso(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)) \
        .strftime("%Y%m%dT%H%M%SZ")


def download_all(repo_root: str = ".", *,
                 downloader=_arxiv_downloader, sleep=time.sleep,
                 retries: int = 3, base_delay: float = POLITE_DELAY_S,
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

    total = len(eligible)
    print(f"pdf: {total} eligible "
          f"(ok={summary['skipped_existing']}, "
          f"cooldown={summary['skipped_cooldown']})",
          file=sys.stderr, flush=True)

    for i, arxiv_id in enumerate(eligible, 1):
        info = status[arxiv_id]
        dest = pdfs_dir / f"{arxiv_id}.pdf"
        info["attempts"] = info.get("attempts", 0) + 1
        info["last_attempt"] = now_iso()
        ok = False
        last_err = None
        server_retry_after = None
        for attempt in range(1, retries + 1):
            try:
                downloader(arxiv_id, str(dest))
                if dest.exists() and dest.stat().st_size > 0:
                    ok = True
                    break
                last_err = "0-byte response"
                if dest.exists():
                    dest.unlink()                  # cleanup corrupt file
            except RateLimited as e:
                last_err = str(e)
                server_retry_after = e.retry_after_seconds
                break                              # don't keep hammering
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
            size_kb = dest.stat().st_size // 1024
            print(f"[{i:4d}/{total}] {arxiv_id}  ok  ({size_kb} KB)",
                  file=sys.stderr, flush=True)
        else:
            info["status"] = "failed"
            info["last_err"] = last_err or "unknown"
            # Respect server Retry-After when given; else use the configured
            # cool-down. Stored as ISO so live queries are readable.
            if server_retry_after is not None:
                ra_iso = (datetime.now(timezone.utc) +
                          timedelta(seconds=server_retry_after)) \
                    .strftime("%Y%m%dT%H%M%SZ")
            else:
                ra_iso = _retry_after_iso(retry_after_hours)
            info["retry_after"] = ra_iso
            summary["failed"] += 1
            tag = "RATE-LIMITED" if server_retry_after is not None else "FAIL"
            print(f"[{i:4d}/{total}] {arxiv_id}  {tag}  {last_err}  "
                  f"retry_after={ra_iso}", file=sys.stderr, flush=True)
            # If the server told us to back off, stop the batch — re-running
            # later will pick up where we left off via skip-cooldown.
            if server_retry_after is not None:
                st.write_pdf_status(status)
                print(f"[bail] server asked for cool-down; stopping batch. "
                      f"Re-run after {ra_iso}.", file=sys.stderr, flush=True)
                break
        # write state after EVERY id so live queries see real progress
        st.write_pdf_status(status)
        sleep(base_delay)

    st.journal({"kind": "pdf", "summary": summary,
                "eligible": len(eligible)})
    print(f"PDF summary: {summary}", file=sys.stderr, flush=True)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--max-ids", type=int, default=None,
                    help="cap how many PDFs to fetch this run (test/throttle)")
    ap.add_argument("--retry-after-hours", type=float, default=4.0,
                    help="cool-down after a failure with no Retry-After header")
    ap.add_argument("--delay", type=float, default=POLITE_DELAY_S,
                    help=f"seconds between requests "
                         f"(default {POLITE_DELAY_S}s = arxiv robots.txt "
                         f"Crawl-delay; lower at your own risk)")
    ns = ap.parse_args(argv)
    download_all(repo_root=ns.repo_root, max_ids=ns.max_ids,
                 retry_after_hours=ns.retry_after_hours,
                 base_delay=ns.delay)


if __name__ == "__main__":
    main()
