"""Per-machine state for the RSS module (gitignored under ``.state/rss/``).

  .state/rss/journal.jsonl       append-only log of actions
  .state/rss/last-fetch.json     { cat: {fetched_at, guid_hash, items} }
  .state/rss/pdf-failures.json   { id : {attempts, last_attempt, last_err,
                                         retry_after} } -- ONLY ids in active
                                cool-down. Removed on success. Owned 100% by
                                the pdf module; no peer ever writes here.
  .state/rss/pdf.pid             PID of the running pdf downloader, written
                                at start, removed at exit; stale-PID-safe.

Design principle: state holds ONLY facts the filesystem cannot represent.
"Should we have this PDF?" → ``data/<pubDate>.jsonl`` (a peer's read-only
artifact). "Do we have it?" → ``pdfs/<id>.pdf`` exists with size > 0.
Anything else (failure history, cool-down clocks, daemon lock) belongs here.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """Filesystem-safe UTC timestamp: ``YYYYMMDDTHHMMSSZ``."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def guid_hash(guids) -> str:
    h = hashlib.sha256()
    for g in sorted(guids):
        h.update(g.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _read_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")


class State:
    """Read/write the small per-machine state under ``.state/rss/``."""

    def __init__(self, repo_root: str = "."):
        self.root = Path(repo_root)
        self.dir = self.root / ".state" / "rss"
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---- journal ----------------------------------------------------------
    def journal(self, event: dict) -> None:
        event = {"ts": now_iso(), **event}
        with (self.dir / "journal.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # ---- last-fetch (early-exit) ------------------------------------------
    def last_fetch(self, cat: str) -> dict | None:
        return _read_json(self.dir / "last-fetch.json").get(cat)

    def set_last_fetch(self, cat: str, fetched_at: str, guid_hash: str,
                       items: int) -> None:
        data = _read_json(self.dir / "last-fetch.json")
        data[cat] = {"fetched_at": fetched_at, "guid_hash": guid_hash,
                     "items": items}
        _write_json(self.dir / "last-fetch.json", data)

    # ---- pdf-failures (only ids in active cool-down) ----------------------
    def pdf_failures(self) -> dict:
        return _read_json(self.dir / "pdf-failures.json")

    def write_pdf_failures(self, data: dict) -> None:
        _write_json(self.dir / "pdf-failures.json", data)

    # ---- pdf daemon pidfile (lock) ---------------------------------------
    def _pid_path(self) -> Path:
        return self.dir / "pdf.pid"

    def pdf_daemon_pid(self) -> int | None:
        """Return the live PID if a daemon is running, else None.
        Stale pidfiles (PID dead) are cleaned up here."""
        p = self._pid_path()
        if not p.exists():
            return None
        try:
            pid = int(p.read_text().strip())
        except (ValueError, OSError):
            p.unlink(missing_ok=True)
            return None
        if not _pid_alive(pid):
            p.unlink(missing_ok=True)
            return None
        return pid

    def pdf_daemon_alive(self) -> bool:
        return self.pdf_daemon_pid() is not None

    def acquire_pdf_pidfile(self) -> bool:
        """Try to claim the pdf-daemon lock. Returns True if we got it,
        False if another daemon already holds a live PID."""
        if self.pdf_daemon_alive():
            return False
        self._pid_path().write_text(str(os.getpid()))
        return True

    def release_pdf_pidfile(self) -> None:
        p = self._pid_path()
        if p.exists():
            try:
                if int(p.read_text().strip()) == os.getpid():
                    p.unlink()
            except (ValueError, OSError):
                p.unlink(missing_ok=True)

    # ---- SOT save (RSS XML, never overwritten) ---------------------------
    def save_sot(self, category: str, xml_bytes: bytes,
                 fetched_at: str) -> Path:
        sot_dir = self.root / "data" / "rss"
        sot_dir.mkdir(parents=True, exist_ok=True)
        p = sot_dir / f"{category}_{fetched_at}.xml"
        p.write_bytes(xml_bytes)
        return p


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True
