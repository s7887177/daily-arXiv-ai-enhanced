import argparse
import json
import sys
import time
from pathlib import Path


def _arxiv_downloader(arxiv_id: str, dest: str) -> None:
    import arxiv
    client = arxiv.Client()
    result = next(client.results(arxiv.Search(id_list=[arxiv_id])))
    d = Path(dest)
    result.download_pdf(dirpath=str(d.parent), filename=d.name)


def _read_ids(jsonl_path: str) -> list[str]:
    ids = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.append(json.loads(line)["id"])
    return ids


def download_all(jsonl_path: str, out_dir: str, *,
                 downloader=_arxiv_downloader, sleep=time.sleep,
                 retries: int = 3, base_delay: float = 3.0) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = {"ok": 0, "skipped": 0, "failed": 0}
    for arxiv_id in _read_ids(jsonl_path):
        dest = out / f"{arxiv_id}.pdf"
        if dest.exists():
            summary["skipped"] += 1
            continue
        for attempt in range(1, retries + 1):
            try:
                downloader(arxiv_id, str(dest))
                summary["ok"] += 1
                break
            except Exception as e:
                if attempt >= retries:
                    print(f"[warn] failed {arxiv_id}: {e}", file=sys.stderr)
                    summary["failed"] += 1
                else:
                    sleep(base_delay * (2 ** (attempt - 1)))
        sleep(base_delay)
    print(f"PDF summary: {summary}", file=sys.stderr)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, help="JSONL produced by crawl")
    p.add_argument("--out-dir", default="pdfs")
    ns = p.parse_args(argv)
    download_all(ns.data, ns.out_dir)


if __name__ == "__main__":
    main()
