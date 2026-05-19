"""Cross-day de-duplication + pipeline gate.

Replacement for daily_arxiv/check_stats.py. Unlike check_stats.py this does
NOT use the wall clock: the "today" date is taken from the --data filename
(the RSS feed pubDate the crawler wrote), so it stays aligned with the
RSS-driven filenames. daily_arxiv/ is left untouched (check_stats.py becomes
unused).

Effect: rewrites the data file in place with papers seen in the prior
HISTORY_DAYS removed (deletes it if everything is duplicate). Exit code is
the pipeline gate, identical contract to check_stats.py:
  0 = has_new_content (continue) | 1 = no_new_content / no_data (stop)
  2 = error
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

HISTORY_DAYS = 7


def _load_ids(path: Path) -> tuple[list[dict], set[str]]:
    papers, ids = [], set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line)
                papers.append(d)
                ids.add(d.get("id", ""))
    return papers, ids


def dedupe(data_path: str, history_days: int = HISTORY_DAYS) -> str:
    data = Path(data_path)
    if not data.exists():
        return "no_data"
    try:
        papers, today_ids = _load_ids(data)
        if not papers:
            return "no_data"

        try:
            day = datetime.strptime(data.stem, "%Y-%m-%d")
        except ValueError:
            print(f"[warn] {data.name} stem is not YYYY-MM-DD; "
                  f"skipping history dedup", file=sys.stderr)
            return "has_new_content"

        history_ids: set[str] = set()
        for i in range(1, history_days + 1):
            prev = data.with_name(
                (day - timedelta(days=i)).strftime("%Y-%m-%d") + ".jsonl")
            if prev.exists():
                _, ids = _load_ids(prev)
                history_ids |= ids

        dup = today_ids & history_ids
        if not dup:
            return "has_new_content"

        kept = [p for p in papers if p.get("id", "") not in dup]
        if kept:
            with data.open("w", encoding="utf-8") as f:
                for p in kept:
                    f.write(json.dumps(p, ensure_ascii=False) + "\n")
            return "has_new_content"
        data.unlink()
        return "no_new_content"
    except Exception as e:  # noqa: BLE001 - report as gate error
        print(f"[error] dedup failed: {e}", file=sys.stderr)
        return "error"


def exit_code(status: str) -> int:
    return {"has_new_content": 0, "no_new_content": 1,
            "no_data": 1, "error": 2}.get(status, 2)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True,
                   help="JSONL produced by crawl (named by feed date)")
    p.add_argument("--history-days", type=int, default=HISTORY_DAYS)
    ns = p.parse_args(argv)
    status = dedupe(ns.data, ns.history_days)
    print(f"dedup: {status}", file=sys.stderr)
    sys.exit(exit_code(status))


if __name__ == "__main__":
    main()
