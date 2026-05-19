import pytest
from daily_arxiv_rss import feeds


def test_feed_url():
    assert feeds.feed_url("cs.AI") == "https://rss.arxiv.org/rss/cs.AI"


def test_sot_path():
    assert feeds.sot_path("data/rss", "cs.AI", "20260518") == "data/rss/cs.AI_20260518.xml"


def test_save_and_read_sot(tmp_path):
    p = tmp_path / "cs.AI_20260518.xml"
    feeds.save_sot(b"<rss/>", p)
    assert p.read_bytes() == b"<rss/>"


def test_fetch_retries_then_succeeds():
    calls = {"n": 0}

    class FakeResp:
        def read(self):
            return b"<rss/>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(url, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            from urllib.error import HTTPError
            raise HTTPError(url, 429, "Too Many Requests", {}, None)
        return FakeResp()

    out = feeds.fetch("http://x", sleep=lambda s: None, retries=5, _opener=fake_open)
    assert out == b"<rss/>"
    assert calls["n"] == 3


def test_fetch_gives_up_after_retries():
    from urllib.error import HTTPError

    def always_429(url, timeout=0):
        raise HTTPError(url, 429, "x", {}, None)

    with pytest.raises(HTTPError):
        feeds.fetch("http://x", sleep=lambda s: None, retries=2, _opener=always_429)
