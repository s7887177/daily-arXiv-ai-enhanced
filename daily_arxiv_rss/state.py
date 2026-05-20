"""Per-machine state for the RSS module (gitignored under ``.state/rss/``).

Three small files plus an append-only event journal:

  .state/rss/journal.jsonl     append-only log of actions (one event per line)
  .state/rss/last-fetch.json   { cat: {fetched_at, guid_hash, items} }
  .state/rss/pdf-status.json   { id : {status, attempts, last_attempt, ...} }

State holds only the facts the filesystem cannot represent: "this PDF failed
and is in cool-down", "the last cs.AI snapshot we observed hashed to X".
Artifacts on disk (``data/<pubDate>.jsonl``, ``data/articles/``, ``pdfs/``)
remain the source of truth for current data.
"""
from __future__ import annotations

import hashlib
import json
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

    # ---- pdf-status -------------------------------------------------------
    def pdf_status(self) -> dict:
        return _read_json(self.dir / "pdf-status.json")

    def write_pdf_status(self, data: dict) -> None:
        _write_json(self.dir / "pdf-status.json", data)

    def queue_pdfs(self, ids) -> int:
        """Mark new ids as ``pending``; existing ids are left alone."""
        status = self.pdf_status()
        added = 0
        for arxiv_id in ids:
            if arxiv_id not in status:
                status[arxiv_id] = {"status": "pending", "attempts": 0}
                added += 1
        self.write_pdf_status(status)
        return added

    # ---- SOT save (RSS XML, never overwritten) ---------------------------
    def save_sot(self, category: str, xml_bytes: bytes,
                 fetched_at: str) -> Path:
        sot_dir = self.root / "data" / "rss"
        sot_dir.mkdir(parents=True, exist_ok=True)
        p = sot_dir / f"{category}_{fetched_at}.xml"
        p.write_bytes(xml_bytes)
        return p
