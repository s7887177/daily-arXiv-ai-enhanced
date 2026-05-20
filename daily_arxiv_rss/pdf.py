"""PDF downloader, self-contained.

The pdf module owns its work. It computes what to fetch from the world's
state, not from a "queue" written by someone else:

  wanted    = union of `id` across every ``data/<pubDate>.jsonl``
              (the crawler's read-only artifact)
  on_disk   = { id : pdfs/<id>.pdf exists AND size > 0 }
              (filesystem == truth of "is this PDF really here")
  failures  = .state/rss/pdf-failures.json
              (only ids in active cool-down — owned by this module)
  eligible  = wanted - on_disk - in_cooldown(failures)

Success leaves no state entry: the PDF on disk IS the success record.
Re-running picks up any wanted-but-missing id (including ones the user
manually deletes). Failures remove themselves from pdf-failures.json on
their first subsequent success.

Politeness: ``arxiv.org/robots.txt`` says ``Crawl-delay: 15`` for the
``*`` user-agent. We honour that as the default per-request delay and
respect ``Retry-After`` on 429/503. /pdf is explicitly Allow'd; we never
touch /api (which the arxiv Python library hit, hung 30s+ on, and which
is Disallow'd anyway).

A pidfile (``.state/rss/pdf.pid``) prevents two downloaders racing on the
same machine; the skill checks it before deciding whether to start one.
"""
from __future__ import annotations

import argparse
import email.utils
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from daily_arxiv_rss.state import State, now_iso

# arxiv.org/robots.txt: Allow /pdf; Crawl-delay: 15 for User-agent *.
_PDF_URL = "https://arxiv.org/pdf/{id}"
_UA = "daily-arxiv-rss/0.1 (educational use; contact via repo)"
_HTTP_TIMEOUT = 60
POLITE_DELAY_S = 15.0


class RateLimited(Exception):
    """Raised on 429/503; carries server-supplied Retry-After (in seconds)."""

    def __init__(self, code: int, retry_after_seconds: float | None):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.retry_after_seconds = retry_after_seconds


def _parse_retry_after(value: str | None) -> float | None:
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

    On 429/503 raises :class:`RateLimited` carrying ``Retry-After``.
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


def wanted_ids(repo_root: str = ".") -> set[str]:
    """Collect ids the crawler said it wanted — union across all per-pubDate
    jsonls under ``data/``."""
    wanted: set[str] = set()
    for jp in sorted(Path(repo_root).glob("data/*.jsonl")):
        with jp.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in r:
                    wanted.add(r["id"])
    return wanted


def on_disk_ids(repo_root: str = ".") -> set[str]:
    """ids whose ``pdfs/<id>.pdf`` exists and has size > 0."""
    out: set[str] = set()
    for p in glob.glob(str(Path(repo_root) / "pdfs" / "*.pdf")):
        try:
            if os.path.getsize(p) > 0:
                out.add(Path(p).stem)
        except OSError:
            continue
    return out


def _eligible(wanted: set[str], have: set[str], failures: dict,
              now: datetime) -> tuple[list[str], int]:
    """Return (eligible_ids_newest_first, n_in_cooldown)."""
    cooldown = 0
    eligible = []
    for arxiv_id in sorted(wanted - have, reverse=True):    # newest-id first
        f = failures.get(arxiv_id)
        if f:
            ra = f.get("retry_after")
            try:
                ra_dt = _iso_to_dt(ra) if ra else None
            except ValueError:
                ra_dt = None
            if ra_dt and now < ra_dt:
                cooldown += 1
                continue
        eligible.append(arxiv_id)
    return eligible, cooldown


def download_all(repo_root: str = ".", *,
                 downloader=_arxiv_downloader, sleep=time.sleep,
                 retries: int = 3, base_delay: float = POLITE_DELAY_S,
                 retry_after_hours: float = 4.0,
                 max_ids: int | None = None,
                 _use_pidfile: bool = True) -> dict:
    """Drain the eligible queue. Filesystem is the source of truth for
    ``wanted`` (jsonl) and ``have`` (pdfs/). State only persists cool-downs."""
    st = State(repo_root)
    summary = {"wanted": 0, "have": 0, "eligible": 0,
               "ok": 0, "skipped_cooldown": 0,
               "fetched_now": 0, "failed": 0, "rate_limited_bail": False}
    if _use_pidfile and not st.acquire_pdf_pidfile():
        other = st.pdf_daemon_pid()
        print(f"[pdf] another downloader is running (pid {other}); exiting.",
              file=sys.stderr, flush=True)
        summary["rate_limited_bail"] = False
        summary["already_running"] = True
        return summary
    try:
        wanted = wanted_ids(repo_root)
        have = on_disk_ids(repo_root)
        failures = st.pdf_failures()
        now = datetime.now(timezone.utc)
        eligible, cooldown = _eligible(wanted, have, failures, now)
        summary["wanted"] = len(wanted)
        summary["have"] = len(wanted & have)
        summary["skipped_cooldown"] = cooldown
        if max_ids is not None:
            eligible = eligible[:max_ids]
        summary["eligible"] = len(eligible)

        (Path(repo_root) / "pdfs").mkdir(exist_ok=True)
        total = len(eligible)
        print(f"pdf: wanted={summary['wanted']} have={summary['have']} "
              f"cooldown={cooldown} eligible={total}",
              file=sys.stderr, flush=True)

        for i, arxiv_id in enumerate(eligible, 1):
            dest = Path(repo_root) / "pdfs" / f"{arxiv_id}.pdf"
            ok = False
            last_err = None
            server_retry_after = None
            attempts = (failures.get(arxiv_id) or {}).get("attempts", 0) + 1
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
                    break                              # don't hammer further
                except Exception as e:
                    last_err = f"{type(e).__name__}: {e}"
                if attempt < retries:
                    sleep(base_delay * (2 ** (attempt - 1)))
            if ok:
                failures.pop(arxiv_id, None)           # success → no state
                summary["ok"] += 1
                summary["fetched_now"] += 1
                size_kb = dest.stat().st_size // 1024
                print(f"[{i:4d}/{total}] {arxiv_id}  ok  ({size_kb} KB)",
                      file=sys.stderr, flush=True)
            else:
                if server_retry_after is not None:
                    ra_iso = (datetime.now(timezone.utc) +
                              timedelta(seconds=server_retry_after)) \
                        .strftime("%Y%m%dT%H%M%SZ")
                else:
                    ra_iso = _retry_after_iso(retry_after_hours)
                failures[arxiv_id] = {
                    "attempts": attempts,
                    "last_attempt": now_iso(),
                    "last_err": last_err or "unknown",
                    "retry_after": ra_iso,
                }
                summary["failed"] += 1
                tag = "RATE-LIMITED" if server_retry_after is not None \
                    else "FAIL"
                print(f"[{i:4d}/{total}] {arxiv_id}  {tag}  {last_err}  "
                      f"retry_after={ra_iso}",
                      file=sys.stderr, flush=True)
                if server_retry_after is not None:
                    st.write_pdf_failures(failures)
                    summary["rate_limited_bail"] = True
                    print(f"[bail] server asked for cool-down; stopping. "
                          f"Re-run after {ra_iso}.",
                          file=sys.stderr, flush=True)
                    break
            # persist after each id so live queries reflect reality
            st.write_pdf_failures(failures)
            sleep(base_delay)

        st.journal({"kind": "pdf", "summary": summary})
        print(f"PDF summary: {summary}", file=sys.stderr, flush=True)
        return summary
    finally:
        if _use_pidfile:
            st.release_pdf_pidfile()


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
