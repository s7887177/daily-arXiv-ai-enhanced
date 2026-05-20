import json
import os

from daily_arxiv_rss.state import State, guid_hash


def test_journal_appends(tmp_path):
    s = State(str(tmp_path))
    s.journal({"kind": "x", "n": 1})
    s.journal({"kind": "y", "n": 2})
    lines = (tmp_path / ".state/rss/journal.jsonl").read_text("utf-8").splitlines()
    assert len(lines) == 2
    e0, e1 = json.loads(lines[0]), json.loads(lines[1])
    assert e0["kind"] == "x" and e1["kind"] == "y"
    assert "ts" in e0 and "ts" in e1


def test_last_fetch_roundtrip(tmp_path):
    s = State(str(tmp_path))
    assert s.last_fetch("cs.AI") is None
    s.set_last_fetch("cs.AI", "20260520T030000Z", "abc", 343)
    s.set_last_fetch("cs.CL", "20260520T030010Z", "def", 200)
    assert s.last_fetch("cs.AI")["guid_hash"] == "abc"
    assert s.last_fetch("cs.CL")["items"] == 200


def test_pdf_failures_roundtrip(tmp_path):
    s = State(str(tmp_path))
    assert s.pdf_failures() == {}
    s.write_pdf_failures({"2605.0001v1":
                          {"attempts": 2, "last_err": "HTTP 429",
                           "retry_after": "20260521T010000Z"}})
    f = s.pdf_failures()
    assert f["2605.0001v1"]["last_err"] == "HTTP 429"


def test_pdf_daemon_lock_lifecycle(tmp_path):
    s = State(str(tmp_path))
    assert s.pdf_daemon_alive() is False
    assert s.pdf_daemon_pid() is None
    assert s.acquire_pdf_pidfile() is True
    assert s.pdf_daemon_alive() is True
    assert s.pdf_daemon_pid() == os.getpid()
    # second acquire by SAME state object should refuse (same machine, same pid live)
    assert s.acquire_pdf_pidfile() is False
    s.release_pdf_pidfile()
    assert s.pdf_daemon_alive() is False
    assert s.pdf_daemon_pid() is None


def test_pdf_daemon_lock_clears_stale_pidfile(tmp_path):
    """A pidfile pointing at a dead pid must be cleaned up automatically."""
    s = State(str(tmp_path))
    pidfile = tmp_path / ".state/rss/pdf.pid"
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text("999999")          # extremely unlikely to be alive
    assert s.pdf_daemon_alive() is False  # stale → swept
    assert not pidfile.exists()
    assert s.acquire_pdf_pidfile() is True
    s.release_pdf_pidfile()


def test_save_sot_versioned(tmp_path):
    s = State(str(tmp_path))
    p1 = s.save_sot("cs.AI", b"<rss/>", "20260520T030000Z")
    p2 = s.save_sot("cs.AI", b"<rss2/>", "20260520T040000Z")
    assert p1.name == "cs.AI_20260520T030000Z.xml"
    assert p2.name == "cs.AI_20260520T040000Z.xml"
    assert p1.exists() and p2.exists()                # never overwrite


def test_guid_hash_is_order_invariant():
    a = guid_hash(["x", "y", "z"])
    b = guid_hash(["z", "y", "x"])
    c = guid_hash(["x", "y"])
    assert a == b
    assert a != c
