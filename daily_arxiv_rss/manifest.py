"""Build the per-pubDate site manifests from the written article markdown.

Each article is filed under **its own paper's pubDate** (the RSS item's
``pubDate`` field, recorded on the record at crawl time). The 5/19 calendar
entry on the site can therefore grow over multiple physical days as arXiv
keeps adding more 5/19-labelled papers (cross-list / replace stragglers).

Inputs (all in repo, no state needed):
  - ``data/<pub_date>.jsonl`` — paper records with ``pub_date`` field.
  - ``data/articles/*.md``  — one article per processed paper.
  - ``data/articles/<pub_date>.json`` (existing) — only used to preserve
    hand-written seed entries that have no corresponding jsonl record.

Outputs:
  - ``data/articles/<pub_date>.json`` (one per pubDate with articles).
  - ``data/articles/index.json`` — dates list (newest first).

CLI:  uv run python -m daily_arxiv_rss.manifest
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

ENTRY_FIELDS = ("id", "arxiv_id", "headline", "hook", "category_label",
                "importance", "authors", "affiliations", "url", "pdf",
                "date", "md")


def _parse_md(path: str) -> tuple[str, str, str, str]:
    txt = Path(path).read_text(encoding="utf-8")
    headline = ""
    for ln in txt.splitlines():
        if ln.startswith("# "):
            headline = ln[2:].strip()
            break
    hook = ""
    m = re.search(r"一句話說重點[：:]\s*(.+)", txt)
    if m:
        hook = m.group(1).strip()
    cat = ""
    m = re.search(r"分類[：:]\s*([^\n]+)", txt)
    if m:
        cat = m.group(1).strip()
    aff = ""
    m = re.search(r"作者[··・]單位[：:]\s*([^\n]+)", txt)
    if m:
        parens = re.findall(r"[（(]([^（）()]+)[）)]", m.group(1))
        if parens:
            aff = "、".join(dict.fromkeys(parens))
    return headline, hook, cat, aff


def _index_records(repo_root: Path) -> dict[str, tuple[str, dict]]:
    """Build ``id → (pub_date, record)`` from every ``data/<date>.jsonl``.

    If a record lacks the ``pub_date`` field (older data), fall back to the
    jsonl filename date.
    """
    out: dict[str, tuple[str, dict]] = {}
    for jp in sorted((repo_root / "data").glob("*.jsonl")):
        file_date = jp.stem                       # e.g. "2026-05-19"
        with jp.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" not in r:
                    continue
                pd = r.get("pub_date") or file_date
                out[r["id"]] = (pd, r)
    return out


def _existing_seed_entries(repo_root: Path) -> dict[str, tuple[str, dict]]:
    """Pick up hand-written manifest entries that have no jsonl record.

    Returns ``id → (date, entry)``.
    """
    out: dict[str, tuple[str, dict]] = {}
    for mp in (repo_root / "data/articles").glob("*.json"):
        if mp.name == "index.json":
            continue
        date = mp.stem
        try:
            data = json.loads(mp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for e in data.get("articles", []):
            if "id" in e:
                out[e["id"]] = (date, e)
    return out


def build(repo_root: str = ".") -> dict:
    root = Path(repo_root)
    id_to_record = _index_records(root)
    seed = _existing_seed_entries(root)

    by_date: dict[str, list[dict]] = {}
    seen_ids: set[str] = set()
    skipped: list[str] = []

    for ap in sorted(glob.glob(str(root / "data/articles/*.md"))):
        sid = Path(ap).stem
        arxiv_id = re.sub(r"v\d+$", "", sid)
        md_rel = f"data/articles/{sid}.md"
        headline, hook, cat, aff = _parse_md(ap)

        if sid in id_to_record:
            date, r = id_to_record[sid]
            au = r.get("authors") or []
            authors = "、".join(au[:6]) + ("等" if len(au) > 6 else "")
            entry = {"id": sid, "arxiv_id": arxiv_id, "headline": headline,
                     "hook": hook,
                     "category_label": cat or (r.get("categories") or [""])[0],
                     "importance": "中", "authors": authors,
                     "affiliations": aff,
                     "url": r.get("abs") or f"https://arxiv.org/abs/{arxiv_id}",
                     "pdf": r.get("pdf") or f"https://arxiv.org/pdf/{arxiv_id}",
                     "date": date, "md": md_rel}
        elif sid in seed:
            date, entry = seed[sid]               # preserve hand-written
        else:
            skipped.append(sid)                   # md with no provenance
            continue

        by_date.setdefault(date, []).append(entry)
        seen_ids.add(sid)

    # write per-pubDate manifests (overwrite each)
    out_dir = root / "data/articles"
    out_dir.mkdir(parents=True, exist_ok=True)
    for date, entries in by_date.items():
        entries.sort(key=lambda e: e["arxiv_id"], reverse=True)
        (out_dir / f"{date}.json").write_text(
            json.dumps({"date": date,
                        "_order": "newest first (by arXiv id desc)",
                        "articles": entries},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")

    # remove any stale per-date manifest whose date has 0 articles now
    for mp in out_dir.glob("*.json"):
        if mp.name == "index.json":
            continue
        if mp.stem not in by_date:
            mp.unlink()

    # update index.json (newest date first)
    dates = sorted(by_date.keys(), reverse=True)
    (out_dir / "index.json").write_text(
        json.dumps({"dates": dates}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    return {"dates": len(dates),
            "articles": sum(len(v) for v in by_date.values()),
            "by_date": {d: len(v) for d, v in by_date.items()},
            "skipped_unknown_pubdate": skipped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    a = ap.parse_args(argv)
    s = build(a.repo_root)
    print(f"manifest: dates={s['dates']} articles={s['articles']}")
    for d in sorted(s["by_date"], reverse=True)[:5]:
        print(f"  {d}: {s['by_date'][d]}")
    if s["skipped_unknown_pubdate"]:
        print(f"  [warn] {len(s['skipped_unknown_pubdate'])} md(s) "
              f"with no jsonl provenance: "
              f"{s['skipped_unknown_pubdate'][:3]}...", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
