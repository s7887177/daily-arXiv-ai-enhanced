import json
from datetime import datetime, timezone, timedelta

from daily_arxiv_rss import status
from daily_arxiv_rss.state import State


def _setup(tmp_path, *, wanted=(), pdfs=(), articles=()):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pdfs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/articles").mkdir(parents=True, exist_ok=True)
    if wanted:
        (tmp_path / "data" / "2026-05-19.jsonl").write_text(
            "\n".join(json.dumps({"id": i}) for i in wanted) + "\n",
            encoding="utf-8")
    for i in pdfs:
        (tmp_path / "pdfs" / f"{i}.pdf").write_bytes(b"%PDF...")
    for i in articles:
        (tmp_path / "data/articles" / f"{i}.md").write_text("# x\n",
                                                            encoding="utf-8")


def test_all_done_when_every_wanted_has_article(tmp_path):
    _setup(tmp_path, wanted=("a", "b"), pdfs=("a", "b"), articles=("a", "b"))
    s = status.snapshot(str(tmp_path))
    assert s["decision"] == "all_done"
    assert s["need_pdfs"] == 0 and s["need_articles"] == 0


def test_write_articles_when_pdfs_ready_articles_missing(tmp_path):
    _setup(tmp_path, wanted=("a", "b"), pdfs=("a", "b"), articles=())
    s = status.snapshot(str(tmp_path))
    assert s["decision"] == "write_articles"
    assert s["have_pdfs"] == 2 and s["need_articles"] == 2


def test_start_pdf_when_missing_and_no_daemon(tmp_path):
    _setup(tmp_path, wanted=("a", "b"), pdfs=("a",))
    s = status.snapshot(str(tmp_path))
    assert s["pdf_daemon_alive"] is False
    assert s["need_pdfs"] == 1
    assert s["decision"] == "start_pdf"


def test_wait_for_pdfs_when_daemon_running(tmp_path):
    _setup(tmp_path, wanted=("a", "b"), pdfs=("a",))
    st = State(str(tmp_path))
    assert st.acquire_pdf_pidfile()
    try:
        s = status.snapshot(str(tmp_path))
        assert s["pdf_daemon_alive"] is True
        # need_articles > 0, need_pdfs > 0, daemon alive → wait or write
        # if some PDF is ready but no article, status will prefer write
        assert s["decision"] in ("wait_for_pdfs", "write_articles")
    finally:
        st.release_pdf_pidfile()


def test_cooldown_counted(tmp_path):
    _setup(tmp_path, wanted=("y",))
    st = State(str(tmp_path))
    future = (datetime.now(timezone.utc) + timedelta(hours=2)) \
        .strftime("%Y%m%dT%H%M%SZ")
    st.write_pdf_failures({"y": {"retry_after": future}})
    s = status.snapshot(str(tmp_path))
    assert s["pdfs_in_cooldown"] == 1


def test_unobtainable_falls_through_to_no_op_or_partial(tmp_path):
    """All remaining PDFs are in cool-down + no daemon → no fetchable work
    right now; articles for available PDFs can still be written."""
    _setup(tmp_path, wanted=("y", "z"), pdfs=("z",))   # y needs pdf, z has
    st = State(str(tmp_path))
    future = (datetime.now(timezone.utc) + timedelta(hours=2)) \
        .strftime("%Y%m%dT%H%M%SZ")
    st.write_pdf_failures({"y": {"retry_after": future}})
    s = status.snapshot(str(tmp_path))
    # z has pdf, no article → still write_articles
    assert s["decision"] == "write_articles"
    assert s["pdfs_in_cooldown"] == 1
