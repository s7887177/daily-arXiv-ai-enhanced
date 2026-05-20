"""Per-pubDate JSONL writer with append-only-by-id semantics.

The new ingestion model files every paper into ``data/<pub_date>.jsonl``
keyed on its own RSS item ``pubDate``. A single crawl can update multiple
pubDate files; an id that's already present is left alone (existing record
wins). This is what replaces the old 7-day window dedup.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


def group_by_pub_date(records) -> dict[str, list[dict]]:
    """Group records by their ``pub_date`` field (YYYY-MM-DD)."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        d = r.get("pub_date") or ""
        if d:
            by_date[d].append(r)
    return dict(by_date)


def merge_jsonl(path, new_records) -> tuple[int, int]:
    """Append-only-by-id merge into ``path``.

    Returns ``(added, total_after)``. Existing ids are preserved verbatim.
    """
    p = Path(path)
    existing: dict[str, dict] = {}
    if p.exists():
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if "id" in r:
                        existing[r["id"]] = r
    added = 0
    for r in new_records:
        if r["id"] not in existing:
            existing[r["id"]] = r
            added += 1
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in existing.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return added, len(existing)


def merge_by_pub_date(records, data_dir: str = "data") -> dict[str, dict]:
    """Group records by pub_date and merge each group into its jsonl.

    Returns ``{pub_date: {added, total}}``.
    """
    summary: dict[str, dict] = {}
    for date, recs in group_by_pub_date(records).items():
        added, total = merge_jsonl(f"{data_dir}/{date}.jsonl", recs)
        summary[date] = {"added": added, "total": total}
    return summary
