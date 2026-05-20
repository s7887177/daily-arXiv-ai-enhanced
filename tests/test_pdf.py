import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from daily_arxiv_rss import pdf
from daily_arxiv_rss.state import State


def _write_jsonl(p: Path, ids):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps({"id": i}) for i in ids) + "\n",
                 encoding="utf-8")


def _wanted(tmp_path, ids):
    """Set up data/<date>.jsonl with the given ids (= what the crawler wants)."""
    _write_jsonl(tmp_path / "data" / "2026-05-19.jsonl", ids)
    (tmp_path / "pdfs").mkdir(parents=True, exist_ok=True)


def test_parse_retry_after_integer_seconds():
    assert pdf._parse_retry_after("120") == 120.0
    assert pdf._parse_retry_after("0") == 0.0
    assert pdf._parse_retry_after(None) is None
    assert pdf._parse_retry_after("garbage") is None


def test_parse_retry_after_http_date():
    import email.utils
    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    val = email.utils.format_datetime(future)
    secs = pdf._parse_retry_after(val)
    assert secs is not None and 50 < secs <= 60


def test_wanted_and_on_disk_helpers(tmp_path):
    _wanted(tmp_path, ["a", "b", "c"])
    (tmp_path / "pdfs/a.pdf").write_bytes(b"%PDF...")
    (tmp_path / "pdfs/c.pdf").write_bytes(b"")          # 0-byte → not "have"
    assert pdf.wanted_ids(str(tmp_path)) == {"a", "b", "c"}
    assert pdf.on_disk_ids(str(tmp_path)) == {"a"}


def test_download_all_skips_existing_pdf(tmp_path):
    """If pdfs/<id>.pdf already exists with size>0, never re-fetch it.
    No state needed — filesystem is truth."""
    _wanted(tmp_path, ["a", "b"])
    (tmp_path / "pdfs/a.pdf").write_bytes(b"%PDF...")
    called = []

    def dl(arxiv_id, dest):
        called.append(arxiv_id)
        open(dest, "wb").write(b"%PDF new")

    s = pdf.download_all(str(tmp_path), downloader=dl,
                         sleep=lambda x: None, _use_pidfile=False)
    assert called == ["b"]
    assert s["wanted"] == 2 and s["have"] == 1 and s["eligible"] == 1
    assert s["ok"] == 1


def test_download_all_picks_up_zero_byte_pdf_as_missing(tmp_path):
    """0-byte file on disk == NOT have. Will be re-fetched."""
    _wanted(tmp_path, ["z"])
    (tmp_path / "pdfs/z.pdf").write_bytes(b"")

    def dl(_, dest):
        open(dest, "wb").write(b"%PDF good")

    s = pdf.download_all(str(tmp_path), downloader=dl,
                         sleep=lambda x: None, _use_pidfile=False)
    assert s["ok"] == 1 and s["fetched_now"] == 1
    assert (tmp_path / "pdfs/z.pdf").read_bytes().startswith(b"%PDF")


def test_success_clears_prior_failure_from_state(tmp_path):
    """A previous failure entry is removed when the id finally succeeds."""
    _wanted(tmp_path, ["x"])
    st = State(str(tmp_path))
    st.write_pdf_failures({"x": {"attempts": 2, "last_err": "boom",
                                 "retry_after": "20200101T000000Z"}})

    def dl(_, dest):
        open(dest, "wb").write(b"%PDF good")

    pdf.download_all(str(tmp_path), downloader=dl,
                     sleep=lambda x: None, _use_pidfile=False)
    assert st.pdf_failures() == {}                  # cleared


def test_failure_writes_failures_entry(tmp_path):
    _wanted(tmp_path, ["x"])

    def dl(_, dest):
        raise RuntimeError("network down")

    pdf.download_all(str(tmp_path), downloader=dl,
                     sleep=lambda x: None, retries=1,
                     _use_pidfile=False)
    f = State(str(tmp_path)).pdf_failures()
    assert "x" in f
    assert f["x"]["last_err"].startswith("RuntimeError")
    assert "retry_after" in f["x"]
    # crucially: NO file at pdfs/x.pdf was left behind
    assert not (tmp_path / "pdfs/x.pdf").exists()


def test_cooldown_skipped(tmp_path):
    _wanted(tmp_path, ["y"])
    st = State(str(tmp_path))
    future = (datetime.now(timezone.utc) + timedelta(hours=2)) \
        .strftime("%Y%m%dT%H%M%SZ")
    st.write_pdf_failures({"y": {"attempts": 1, "retry_after": future,
                                 "last_err": "429"}})
    called = []

    def dl(arxiv_id, dest):
        called.append(arxiv_id)

    s = pdf.download_all(str(tmp_path), downloader=dl,
                         sleep=lambda x: None, _use_pidfile=False)
    assert called == []                              # cool-down respected
    assert s["skipped_cooldown"] == 1 and s["eligible"] == 0


def test_rate_limited_bails_and_respects_server_retry_after(tmp_path):
    _wanted(tmp_path, ["x", "y", "z"])
    calls = []

    def dl(arxiv_id, dest):
        calls.append(arxiv_id)
        if arxiv_id == "z":                          # newest-first, so z first
            raise pdf.RateLimited(429, 90.0)
        open(dest, "wb").write(b"%PDF ok")

    s = pdf.download_all(str(tmp_path), downloader=dl,
                         sleep=lambda x: None, retries=1,
                         _use_pidfile=False)
    assert calls == ["z"]                            # bails on first 429
    assert s["failed"] == 1 and s["rate_limited_bail"] is True
    f = State(str(tmp_path)).pdf_failures()
    assert "z" in f and f["z"]["last_err"].startswith("HTTP 429")
    # x and y untouched
    assert "x" not in f and "y" not in f
    assert not (tmp_path / "pdfs/x.pdf").exists()


def test_pidfile_prevents_double_start(tmp_path):
    _wanted(tmp_path, ["a"])
    st = State(str(tmp_path))
    assert st.acquire_pdf_pidfile() is True          # simulate another daemon
    try:
        called = []
        s = pdf.download_all(str(tmp_path),
                             downloader=lambda i, d: called.append(i),
                             sleep=lambda x: None, _use_pidfile=True)
        assert called == []
        assert s.get("already_running") is True
    finally:
        st.release_pdf_pidfile()


def test_wanted_minus_have_is_newest_first(tmp_path):
    _wanted(tmp_path, ["2605.10001v1", "2605.10003v1", "2605.10002v1"])
    order = []

    def dl(arxiv_id, dest):
        order.append(arxiv_id)
        open(dest, "wb").write(b"%PDF ok")

    pdf.download_all(str(tmp_path), downloader=dl,
                     sleep=lambda x: None, _use_pidfile=False)
    assert order == ["2605.10003v1", "2605.10002v1", "2605.10001v1"]
