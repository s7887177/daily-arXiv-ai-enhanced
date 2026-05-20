"""Split the remaining work into per-subagent worklists (resumable, parallel).

A day is large, so ``/daily-digest`` is run as parallel subagent waves. This
picks papers whose PDF is downloaded and whole, that have no article yet,
newest arXiv id first (across **all** per-pubDate jsonls), and writes one
``agent-NN.jsonl`` per subagent.

Also prunes 0-byte PDFs (a corrupt download arXiv sometimes serves; the bulk
downloader's skip-existing does NOT detect these) so they get refetched.

CLI:  uv run python -m daily_arxiv_rss.wave --wave 100 --per 10
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pathlib
import sys
import time


def prune_empty_pdfs(pdfs_dir: str = "pdfs") -> list[str]:
    removed = []
    for p in glob.glob(f"{pdfs_dir}/*.pdf"):
        if os.path.getsize(p) == 0:
            os.remove(p)
            removed.append(pathlib.Path(p).stem)
    return removed


def _load_all_records(root: pathlib.Path) -> dict[str, dict]:
    """Read every ``data/<pubdate>.jsonl`` and return ``id → record``."""
    recs: dict[str, dict] = {}
    for jp in sorted((root / "data").glob("*.jsonl")):
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
                    recs[r["id"]] = r
    return recs


def build_waves(wave_size: int, per_agent: int,
                out_dir: str = "/tmp/digest-wave",
                repo_root: str = ".",
                min_pdf_bytes: int = 1000,
                min_age_s: float = 8.0) -> dict:
    root = pathlib.Path(repo_root)
    prune_empty_pdfs(str(root / "pdfs"))

    recs = _load_all_records(root)
    have_md = {p.stem for p in (root / "data/articles").glob("*.md")}
    now = time.time()
    stable = []
    for p in glob.glob(str(root / "pdfs/*.pdf")):
        st = os.stat(p)
        sid = pathlib.Path(p).stem
        if (st.st_size > min_pdf_bytes and now - st.st_mtime > min_age_s
                and sid not in have_md and sid in recs):
            stable.append(sid)
    stable.sort(reverse=True)                      # newest arXiv id first
    pick = stable[:wave_size]

    wdir = pathlib.Path(out_dir)
    if wdir.exists():
        for f in wdir.glob("agent-*.jsonl"):
            f.unlink()
    wdir.mkdir(parents=True, exist_ok=True)
    groups = [pick[i:i + per_agent] for i in range(0, len(pick), per_agent)]
    for i, g in enumerate(groups):
        with open(wdir / f"agent-{i:02d}.jsonl", "w", encoding="utf-8") as fh:
            for sid in g:
                fh.write(json.dumps(recs[sid], ensure_ascii=False) + "\n")

    return {"stable_available": len(stable), "picked": len(pick),
            "agents": len(groups), "out_dir": str(wdir),
            "groups": [(f"agent-{i:02d}", g) for i, g in enumerate(groups)]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wave", type=int, default=100, help="papers this wave")
    ap.add_argument("--per", type=int, default=10, help="papers per subagent")
    ap.add_argument("--out", default="/tmp/digest-wave")
    ap.add_argument("--repo-root", default=".")
    a = ap.parse_args(argv)
    s = build_waves(a.wave, a.per, a.out, a.repo_root)
    print(f"stable_available={s['stable_available']} picked={s['picked']} "
          f"agents={s['agents']} out={s['out_dir']}")
    for name, g in s["groups"]:
        if g:
            print(f"{name}: {len(g)} ids  [{g[0]} .. {g[-1]}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
