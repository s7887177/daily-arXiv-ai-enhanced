"""Build the per-day site manifest from the written article markdown.

Scans ``data/articles/*.md``, pulls the headline / one-line hook / category
from each article, joins paper metadata from ``data/<date>.jsonl`` when
available, and writes ``data/articles/<date>.json`` (newest arXiv id first).
Hand-written entries already in the manifest that are NOT in today's crawl
(e.g. seed sample articles) are preserved verbatim. Also ensures ``<date>``
is present in ``data/articles/index.json``.

CLI:  uv run python -m daily_arxiv_rss.manifest --date 2026-05-19
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import re
import sys

ENTRY_FIELDS = ("id", "arxiv_id", "headline", "hook", "category_label",
                "importance", "authors", "affiliations", "url", "pdf",
                "date", "md")


def _parse_md(path: str) -> tuple[str, str, str, str]:
    txt = open(path, encoding="utf-8").read()
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


def build(date: str, repo_root: str = ".") -> dict:
    root = pathlib.Path(repo_root)
    recs: dict[str, dict] = {}
    jsonl = root / f"data/{date}.jsonl"
    if jsonl.exists():
        for line in open(jsonl, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                recs[r["id"]] = r

    mp = root / f"data/articles/{date}.json"
    prev: dict[str, dict] = {}
    if mp.exists():
        for e in json.load(open(mp, encoding="utf-8")).get("articles", []):
            prev[e["id"]] = e

    arts = []
    for p in sorted(glob.glob(str(root / "data/articles/*.md"))):
        sid = pathlib.Path(p).stem
        arxiv_id = re.sub(r"v\d+$", "", sid)
        headline, hook, cat, aff = _parse_md(p)
        md_rel = f"data/articles/{sid}.md"
        if sid in recs:
            r = recs[sid]
            au = r.get("authors") or []
            authors = "、".join(au[:6]) + ("等" if len(au) > 6 else "")
            e = {"id": sid, "arxiv_id": arxiv_id, "headline": headline,
                 "hook": hook,
                 "category_label": cat or (r.get("categories") or [""])[0],
                 "importance": "中", "authors": authors, "affiliations": aff,
                 "url": r.get("abs") or f"https://arxiv.org/abs/{arxiv_id}",
                 "pdf": r.get("pdf") or f"https://arxiv.org/pdf/{arxiv_id}",
                 "date": date, "md": md_rel}
        elif sid in prev:
            e = prev[sid]                       # keep hand-written entry intact
        else:
            e = {"id": sid, "arxiv_id": arxiv_id, "headline": headline,
                 "hook": hook, "category_label": cat, "importance": "中",
                 "authors": "", "affiliations": aff,
                 "url": f"https://arxiv.org/abs/{arxiv_id}",
                 "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
                 "date": date, "md": md_rel}
        arts.append(e)

    arts.sort(key=lambda e: e["arxiv_id"], reverse=True)   # newest first
    mp.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"date": date, "_order": "newest first (by arXiv id desc)",
               "articles": arts},
              open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    idx = root / "data/articles/index.json"
    ix = json.load(open(idx, encoding="utf-8")) if idx.exists() else {"dates": []}
    if date not in ix["dates"]:
        ix["dates"].insert(0, date)
    ix["dates"].sort(reverse=True)              # newest date first
    json.dump(ix, open(idx, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    return {"articles": len(arts),
            "jsonl_matched": sum(1 for a in arts if a["id"] in recs),
            "preserved": sum(1 for a in arts
                             if a["id"] in prev and a["id"] not in recs)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="feed date, e.g. 2026-05-19")
    ap.add_argument("--repo-root", default=".")
    a = ap.parse_args(argv)
    s = build(a.date, a.repo_root)
    print(f"manifest articles={s['articles']} "
          f"(jsonl-matched={s['jsonl_matched']}, preserved={s['preserved']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
