from datetime import datetime, timezone, timedelta

from daily_arxiv_rss import pdf
from daily_arxiv_rss.state import State


def test_parse_retry_after_integer_seconds():
    assert pdf._parse_retry_after("120") == 120.0
    assert pdf._parse_retry_after("0") == 0.0
    assert pdf._parse_retry_after(None) is None
    assert pdf._parse_retry_after("garbage") is None


def test_parse_retry_after_http_date():
    # HTTP-date 60s in the future → ~60s remaining (allow a tiny delta)
    import email.utils
    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    val = email.utils.format_datetime(future)
    secs = pdf._parse_retry_after(val)
    assert secs is not None and 50 < secs <= 60


def test_rate_limited_bails_and_respects_retry_after(tmp_path):
    """A 429 with Retry-After must stop the batch and use server's value."""
    st = State(str(tmp_path))
    st.queue_pdfs(["x", "y", "z"])
    (tmp_path / "pdfs").mkdir()

    calls = []
    def dl(arxiv_id, dest):
        calls.append(arxiv_id)
        if arxiv_id == "x":                       # first id 429s
            raise pdf.RateLimited(429, 90.0)      # server says wait 90s
        open(dest, "wb").write(b"%PDF ok")

    summary = pdf.download_all(str(tmp_path), downloader=dl,
                               sleep=lambda s: None, retries=1)
    # x was attempted then bail → y and z never tried this run
    assert calls == ["x"]
    assert summary["failed"] == 1 and summary["ok"] == 0
    s = st.pdf_status()
    assert s["x"]["status"] == "failed"
    assert s["x"]["last_err"].startswith("HTTP 429")
    assert "retry_after" in s["x"]                # set from server's 90s
    # y, z still pending (untouched this run)
    assert s["y"]["status"] == "pending"
    assert s["z"]["status"] == "pending"


def test_download_all_skips_existing_ok(tmp_path):
    st = State(str(tmp_path))
    st.queue_pdfs(["a", "b"])
    (tmp_path / "pdfs").mkdir()
    s = st.pdf_status()
    s["a"] = {"status": "ok", "attempts": 1}
    st.write_pdf_status(s)
    (tmp_path / "pdfs/a.pdf").write_bytes(b"%PDF...")

    called = []

    def dl(arxiv_id, dest):
        called.append(arxiv_id)
        open(dest, "wb").write(b"%PDF new")

    summary = pdf.download_all(str(tmp_path), downloader=dl,
                               sleep=lambda s: None)
    assert called == ["b"]                                    # only b attempted
    assert summary["ok"] == 1 and summary["skipped_existing"] == 1


def test_download_all_failure_sets_cooldown(tmp_path):
    st = State(str(tmp_path))
    st.queue_pdfs(["x"])
    (tmp_path / "pdfs").mkdir()

    def dl(_, dest):
        raise RuntimeError("HTTP 429")

    summary = pdf.download_all(str(tmp_path), downloader=dl,
                               sleep=lambda s: None, retries=1,
                               retry_after_hours=2.0)
    assert summary["failed"] == 1
    s = st.pdf_status()
    assert s["x"]["status"] == "failed"
    assert s["x"]["last_err"].startswith("RuntimeError")
    assert "retry_after" in s["x"]


def test_download_all_skips_cooldown(tmp_path):
    st = State(str(tmp_path))
    st.queue_pdfs(["y"])
    (tmp_path / "pdfs").mkdir()
    s = st.pdf_status()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)) \
        .strftime("%Y%m%dT%H%M%SZ")
    s["y"] = {"status": "failed", "attempts": 1, "retry_after": future,
              "last_err": "429"}
    st.write_pdf_status(s)

    called = []

    def dl(arxiv_id, dest):
        called.append(arxiv_id)

    summary = pdf.download_all(str(tmp_path), downloader=dl,
                               sleep=lambda s: None)
    assert called == []                                        # cool-down respected
    assert summary["skipped_cooldown"] == 1


def test_download_all_recovers_zero_byte_existing(tmp_path):
    """An "ok" id whose file went missing/zero gets retried."""
    st = State(str(tmp_path))
    st.queue_pdfs(["z"])
    (tmp_path / "pdfs").mkdir()
    s = st.pdf_status()
    s["z"] = {"status": "ok", "attempts": 1}
    st.write_pdf_status(s)
    (tmp_path / "pdfs/z.pdf").write_bytes(b"")                 # corrupt

    def dl(_, dest):
        open(dest, "wb").write(b"%PDF good")

    summary = pdf.download_all(str(tmp_path), downloader=dl,
                               sleep=lambda s: None)
    assert summary["ok"] == 1 and summary["fetched_now"] == 1
    assert (tmp_path / "pdfs/z.pdf").read_bytes().startswith(b"%PDF")
