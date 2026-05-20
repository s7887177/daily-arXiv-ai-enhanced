import json

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


def test_queue_pdfs_only_adds_new(tmp_path):
    s = State(str(tmp_path))
    added = s.queue_pdfs(["a", "b"])
    assert added == 2
    s.write_pdf_status({**s.pdf_status(),
                        "a": {"status": "ok", "attempts": 1}})
    added2 = s.queue_pdfs(["a", "b", "c"])
    assert added2 == 1                                # only "c" was new
    assert s.pdf_status()["a"]["status"] == "ok"      # not clobbered


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
