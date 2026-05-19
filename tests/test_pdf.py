import json
from daily_arxiv_rss import pdf


def _write_jsonl(p, ids):
    p.write_text("\n".join(json.dumps({"id": i}) for i in ids) + "\n",
                 encoding="utf-8")


def test_download_all_skips_existing_and_calls_downloader(tmp_path):
    data = tmp_path / "2026-05-18.jsonl"
    _write_jsonl(data, ["2605.15204v1", "2605.15202v1"])
    out = tmp_path / "pdfs"
    out.mkdir()
    (out / "2605.15204v1.pdf").write_bytes(b"%PDF exists")
    called = []

    def downloader(arxiv_id, dest):
        called.append(arxiv_id)
        open(dest, "wb").write(b"%PDF new")

    pdf.download_all(str(data), str(out), downloader=downloader,
                     sleep=lambda s: None)
    assert called == ["2605.15202v1"]
    assert (out / "2605.15202v1.pdf").read_bytes() == b"%PDF new"


def test_download_all_failure_is_non_fatal(tmp_path):
    data = tmp_path / "d.jsonl"
    _write_jsonl(data, ["2605.0001v1", "2605.0002v1"])
    out = tmp_path / "pdfs"
    out.mkdir()

    def downloader(arxiv_id, dest):
        if arxiv_id == "2605.0001v1":
            raise RuntimeError("boom")
        open(dest, "wb").write(b"ok")

    summary = pdf.download_all(str(data), str(out), downloader=downloader,
                               sleep=lambda s: None, retries=1)
    assert summary["ok"] == 1 and summary["failed"] == 1
    assert (out / "2605.0002v1.pdf").exists()
