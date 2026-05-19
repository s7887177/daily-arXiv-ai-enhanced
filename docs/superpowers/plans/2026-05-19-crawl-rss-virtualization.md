# Crawl Step RSS Virtualization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Scrapy crawl step with an RSS-based `daily_arxiv_rss/` module that preserves the existing JSONL contract, plus a manual local-only PDF downloader.

**Architecture:** Two units — Fetch (RSS → stored SOT XML under `data/rss/`) and Transform (SOT → 8-field JSONL). A CLI orchestrator is what `run.sh`/`run.yml` invoke. A separate manual PDF tool consumes the produced JSONL. `daily_arxiv/` is untouched; downstream stages unchanged.

**Tech Stack:** Python ≥3.12 (project `.venv`, `uv`), stdlib `xml.etree.ElementTree` + `urllib`, `arxiv` lib (already a dep) for PDF download, `pytest` (added dev-dep) for TDD.

**Spec:** `docs/superpowers/specs/2026-05-19-crawl-rss-interface-design.md`

**Scope clarification (justified additive deviation):** Spec §3 says "only run.sh and run.yml may change." Creating `daily_arxiv_rss/`, `tests/`, a `.gitignore` entry, and adding `pytest` as a **dev-only** dependency are all additive and required for TDD. Runtime deps and `daily_arxiv/` are NOT touched. `scrapy` stays in `pyproject.toml`.

**Run commands from repo root.** Tests run in the project venv: `uv run pytest ...` (system python is 3.10; project needs 3.12).

---

## File Structure

```
daily_arxiv_rss/
  __init__.py         # empty package marker
  parse.py            # RSS XML bytes -> list[RawItem] (namespace-agnostic)
  transform.py        # RawItem(s) -> 8-field contract records; cross-primary; assembly dedup; JSONL writer
  feeds.py            # feed URL building; gentle HTTP fetch; SOT read/write
  crawl.py            # CLI: orchestrate fetch->SOT->transform->write JSONL  (run.sh/run.yml target)
  pdf.py              # CLI: manual PDF downloader (spec §11)
tests/
  __init__.py
  conftest.py         # fixture loader
  fixtures/
    cs.AI_sample.xml  # real-shape RSS fixture (new + cross items)
    cs.CL_sample.xml  # feed where the cross paper is "new" (primary resolution)
  test_parse.py
  test_transform.py
  test_feeds.py
  test_crawl.py
  test_pdf.py
```

Contract record = dict with EXACTLY these keys: `id, categories, pdf, abs, authors, title, comment, summary` (spec §2.3, §4.3). `announce_type` is carried internally on `RawItem` but never written to output.

---

## Task 0: Scaffolding

**Files:**
- Create: `daily_arxiv_rss/__init__.py`, `tests/__init__.py`, `tests/conftest.py`
- Create: `tests/fixtures/cs.AI_sample.xml`, `tests/fixtures/cs.CL_sample.xml`
- Modify: `pyproject.toml` (add dev pytest), `.gitignore` (add `pdfs/`)

- [ ] **Step 1: Create package + test dirs**

```bash
mkdir -p daily_arxiv_rss tests/fixtures
touch daily_arxiv_rss/__init__.py tests/__init__.py
```

- [ ] **Step 2: Add pytest dev dependency**

Run: `uv add --dev pytest`
Expected: `pyproject.toml` gains a dev dependency group with `pytest`; `uv.lock` updated; exit 0.

- [ ] **Step 3: Add `pdfs/` to .gitignore**

Append to `.gitignore` (create the line if absent):

```
pdfs/
```

- [ ] **Step 4: Write the cs.AI fixture** — `tests/fixtures/cs.AI_sample.xml`

Contains 3 items: one `new` (single category), one `new` (multi-category, cs.AI primary), one `cross` (cs.AI listed first but primary is cs.CL — the resolution test case).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<title>cs.AI</title>
<item>
<title>SDOF: Taming the Alignment Tax</title>
<link>https://arxiv.org/abs/2605.15204</link>
<description>arXiv:2605.15204v1 Announce Type: new 
Abstract: We present a constrained state machine framework for multi-agent execution.</description>
<guid isPermaLink="false">oai:arXiv.org:2605.15204v1</guid>
<category>cs.AI</category>
<pubDate>Mon, 18 May 2026 00:00:00 -0400</pubDate>
<arxiv:announce_type>new</arxiv:announce_type>
<dc:creator>Zhantao Wang</dc:creator>
</item>
<item>
<title>CAX-Agent: A Lightweight Agent Harness</title>
<link>https://arxiv.org/abs/2605.15218</link>
<description>arXiv:2605.15218v1 Announce Type: new 
Abstract: Large language models deployed for MAPDL finite-element simulation face reliability challenges.</description>
<guid isPermaLink="false">oai:arXiv.org:2605.15218v1</guid>
<category>cs.AI</category>
<category>cs.CE</category>
<pubDate>Mon, 18 May 2026 00:00:00 -0400</pubDate>
<arxiv:announce_type>new</arxiv:announce_type>
<dc:creator>Chenying Lin, Yichen Hai, Yi He</dc:creator>
</item>
<item>
<title>DeepSlide: From Artifacts to Presentation Delivery</title>
<link>https://arxiv.org/abs/2605.15202</link>
<description>arXiv:2605.15202v1 Announce Type: cross 
Abstract: We present DeepSlide, a human-in-the-loop multi-agent system.</description>
<guid isPermaLink="false">oai:arXiv.org:2605.15202v1</guid>
<category>cs.AI</category>
<category>cs.CL</category>
<category>cs.IR</category>
<pubDate>Mon, 18 May 2026 00:00:00 -0400</pubDate>
<arxiv:announce_type>cross</arxiv:announce_type>
<dc:creator>Ming Yang, Zhiwei Zhang</dc:creator>
</item>
</channel>
</rss>
```

- [ ] **Step 5: Write the cs.CL fixture** — `tests/fixtures/cs.CL_sample.xml`

Same paper `2605.15202` appears here as `new` (cs.CL is its true primary). This is what cross-resolution uses.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<title>cs.CL</title>
<item>
<title>DeepSlide: From Artifacts to Presentation Delivery</title>
<link>https://arxiv.org/abs/2605.15202</link>
<description>arXiv:2605.15202v1 Announce Type: new 
Abstract: We present DeepSlide, a human-in-the-loop multi-agent system.</description>
<guid isPermaLink="false">oai:arXiv.org:2605.15202v1</guid>
<category>cs.CL</category>
<category>cs.AI</category>
<category>cs.IR</category>
<pubDate>Mon, 18 May 2026 00:00:00 -0400</pubDate>
<arxiv:announce_type>new</arxiv:announce_type>
<dc:creator>Ming Yang, Zhiwei Zhang</dc:creator>
</item>
</channel>
</rss>
```

- [ ] **Step 6: Write `tests/conftest.py`**

```python
from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture
def cs_ai_xml() -> bytes:
    return (FIXTURES / "cs.AI_sample.xml").read_bytes()

@pytest.fixture
def cs_cl_xml() -> bytes:
    return (FIXTURES / "cs.CL_sample.xml").read_bytes()
```

- [ ] **Step 7: Commit**

```bash
git add daily_arxiv_rss/ tests/ pyproject.toml uv.lock .gitignore
git commit -m "chore: scaffold daily_arxiv_rss package, pytest, fixtures"
```

---

## Task 1: RSS parsing (`parse.py`)

**Files:**
- Create: `daily_arxiv_rss/parse.py`
- Test: `tests/test_parse.py`

`RawItem` is a dataclass with: `guid: str`, `link: str`, `title: str`, `description: str`, `categories: list[str]`, `announce_type: str`, `dc_creator: str`. Parsing is namespace-agnostic (match by local tag name via `tag.split('}')[-1]`).

- [ ] **Step 1: Write the failing test** — `tests/test_parse.py`

```python
from daily_arxiv_rss.parse import parse_feed

def test_parse_feed_extracts_items(cs_ai_xml):
    items = parse_feed(cs_ai_xml)
    assert len(items) == 3
    first = items[0]
    assert first.guid == "oai:arXiv.org:2605.15204v1"
    assert first.link == "https://arxiv.org/abs/2605.15204"
    assert first.title == "SDOF: Taming the Alignment Tax"
    assert first.announce_type == "new"
    assert first.categories == ["cs.AI"]
    assert first.dc_creator == "Zhantao Wang"
    assert "constrained state machine" in first.description

def test_parse_feed_multi_category_order_preserved(cs_ai_xml):
    items = parse_feed(cs_ai_xml)
    cross = items[2]
    assert cross.announce_type == "cross"
    assert cross.categories == ["cs.AI", "cs.CL", "cs.IR"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'daily_arxiv_rss.parse'`

- [ ] **Step 3: Write minimal implementation** — `daily_arxiv_rss/parse.py`

```python
from dataclasses import dataclass, field
import xml.etree.ElementTree as ET


@dataclass
class RawItem:
    guid: str
    link: str
    title: str
    description: str
    categories: list[str] = field(default_factory=list)
    announce_type: str = ""
    dc_creator: str = ""


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def parse_feed(xml_bytes: bytes) -> list[RawItem]:
    root = ET.fromstring(xml_bytes)
    items: list[RawItem] = []
    for item_el in root.iter():
        if _local(item_el.tag) != "item":
            continue
        data = {"guid": "", "link": "", "title": "", "description": "",
                "announce_type": "", "dc_creator": ""}
        categories: list[str] = []
        for child in item_el:
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "category":
                if text:
                    categories.append(text)
            elif name == "announce_type":
                data["announce_type"] = text
            elif name == "creator":
                data["dc_creator"] = text
            elif name in data:
                data[name] = text
        items.append(RawItem(categories=categories, **data))
    return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_parse.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add daily_arxiv_rss/parse.py tests/test_parse.py
git commit -m "feat: RSS feed parser (namespace-agnostic)"
```

---

## Task 2: Single-item → contract record (`transform.py`)

**Files:**
- Create: `daily_arxiv_rss/transform.py`
- Test: `tests/test_transform.py`

`to_record(item: RawItem) -> dict` builds the 8-field record (no cross resolution yet — categories in feed order).

- [ ] **Step 1: Write the failing test** — `tests/test_transform.py`

```python
from daily_arxiv_rss.parse import parse_feed
from daily_arxiv_rss.transform import to_record

def test_to_record_maps_all_eight_fields(cs_ai_xml):
    items = parse_feed(cs_ai_xml)
    rec = to_record(items[1])  # 2605.15218v1, two categories
    assert set(rec.keys()) == {"id", "categories", "pdf", "abs",
                               "authors", "title", "comment", "summary"}
    assert rec["id"] == "2605.15218v1"
    assert rec["abs"] == "https://arxiv.org/abs/2605.15218"
    assert rec["pdf"] == "https://arxiv.org/pdf/2605.15218"
    assert rec["title"] == "CAX-Agent: A Lightweight Agent Harness"
    assert rec["authors"] == ["Chenying Lin", "Yichen Hai", "Yi He"]
    assert rec["categories"] == ["cs.AI", "cs.CE"]
    assert rec["comment"] is None
    assert rec["summary"].startswith("Large language models deployed")
    assert "Announce Type" not in rec["summary"]

def test_to_record_strips_oai_prefix_keeps_version(cs_ai_xml):
    rec = to_record(parse_feed(cs_ai_xml)[0])
    assert rec["id"] == "2605.15204v1"  # versioned, no oai: prefix
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_transform.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'daily_arxiv_rss.transform'`

- [ ] **Step 3: Write minimal implementation** — `daily_arxiv_rss/transform.py`

```python
import re
from daily_arxiv_rss.parse import RawItem

_OAI_PREFIX = "oai:arXiv.org:"
_VERSION_RE = re.compile(r"v\d+$")


def _versioned_id(guid: str) -> str:
    return guid.removeprefix(_OAI_PREFIX).strip()


def _bare_id(versioned: str) -> str:
    return _VERSION_RE.sub("", versioned)


def _summary(description: str) -> str:
    marker = "Abstract: "
    idx = description.find(marker)
    if idx != -1:
        return description[idx + len(marker):].strip()
    return description.strip()


def _authors(dc_creator: str) -> list[str]:
    return [a.strip() for a in dc_creator.split(",") if a.strip()]


def to_record(item: RawItem) -> dict:
    vid = _versioned_id(item.guid)
    bare = _bare_id(vid)
    return {
        "id": vid,
        "categories": list(item.categories),
        "pdf": f"https://arxiv.org/pdf/{bare}",
        "abs": item.link,
        "authors": _authors(item.dc_creator),
        "title": item.title,
        "comment": None,
        "summary": _summary(item.description),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_transform.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add daily_arxiv_rss/transform.py tests/test_transform.py
git commit -m "feat: RawItem -> 8-field contract record mapping"
```

---

## Task 3: Cross-primary resolution (`transform.py`)

**Files:**
- Modify: `daily_arxiv_rss/transform.py`
- Test: `tests/test_transform.py` (add)

`resolve_primary(records_by_feed, announce_index)` reorders a cross item's `categories` so the true primary (the feed where the same guid is `new`) is `categories[0]`. Fallback: leave order unchanged.

- [ ] **Step 1: Write the failing test** — append to `tests/test_transform.py`

```python
from daily_arxiv_rss.transform import build_announce_index, resolved_categories
from daily_arxiv_rss.parse import parse_feed

def test_cross_primary_resolution(cs_ai_xml, cs_cl_xml):
    feeds = {"cs.AI": parse_feed(cs_ai_xml), "cs.CL": parse_feed(cs_cl_xml)}
    idx = build_announce_index(feeds)
    cross = parse_feed(cs_ai_xml)[2]  # 2605.15202v1, cross in cs.AI
    cats = resolved_categories(cross, idx)
    assert cats[0] == "cs.CL"  # cs.CL feed has it as 'new' -> primary
    assert set(cats) == {"cs.AI", "cs.CL", "cs.IR"}

def test_cross_primary_fallback_keeps_order(cs_ai_xml):
    feeds = {"cs.AI": parse_feed(cs_ai_xml)}  # cs.CL feed NOT available
    idx = build_announce_index(feeds)
    cross = parse_feed(cs_ai_xml)[2]
    cats = resolved_categories(cross, idx)
    assert cats == ["cs.AI", "cs.CL", "cs.IR"]  # unchanged fallback

def test_resolved_categories_noop_for_new_item(cs_ai_xml):
    feeds = {"cs.AI": parse_feed(cs_ai_xml)}
    idx = build_announce_index(feeds)
    new_item = parse_feed(cs_ai_xml)[1]
    assert resolved_categories(new_item, idx) == ["cs.AI", "cs.CE"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_transform.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_announce_index'`

- [ ] **Step 3: Add implementation** — append to `daily_arxiv_rss/transform.py`

```python
def build_announce_index(feeds: dict[str, list[RawItem]]) -> dict[str, dict[str, str]]:
    """category -> { versioned_id : announce_type }"""
    index: dict[str, dict[str, str]] = {}
    for category, items in feeds.items():
        index[category] = {
            _versioned_id(it.guid): it.announce_type for it in items
        }
    return index


def resolved_categories(item: RawItem, announce_index: dict[str, dict[str, str]]) -> list[str]:
    cats = list(item.categories)
    if item.announce_type != "cross":
        return cats
    vid = _versioned_id(item.guid)
    for cat in cats:
        feed = announce_index.get(cat)
        if feed and feed.get(vid) == "new":
            return [cat] + [c for c in cats if c != cat]
    return cats  # fallback: order unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_transform.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add daily_arxiv_rss/transform.py tests/test_transform.py
git commit -m "feat: cross-list primary category resolution via RSS"
```

---

## Task 4: Assembly dedup + JSONL writer (`transform.py`)

**Files:**
- Modify: `daily_arxiv_rss/transform.py`
- Test: `tests/test_transform.py` (add)

`assemble(requested_feeds, announce_index) -> list[dict]`: for each item in the requested feeds, build record with resolved categories; collapse duplicate `id` (keep first). `write_jsonl(records, path)`: one `json.dumps(rec, ensure_ascii=False)` per line + `\n`, UTF-8.

- [ ] **Step 1: Write the failing test** — append to `tests/test_transform.py`

```python
import json
from daily_arxiv_rss.transform import assemble, write_jsonl

def test_assemble_dedups_by_id_and_resolves(cs_ai_xml, cs_cl_xml):
    requested = {"cs.AI": parse_feed(cs_ai_xml)}
    all_feeds = {"cs.AI": parse_feed(cs_ai_xml), "cs.CL": parse_feed(cs_cl_xml)}
    idx = build_announce_index(all_feeds)
    recs = assemble(requested, idx)
    ids = [r["id"] for r in recs]
    assert ids == ["2605.15204v1", "2605.15218v1", "2605.15202v1"]
    cross = [r for r in recs if r["id"] == "2605.15202v1"][0]
    assert cross["categories"][0] == "cs.CL"

def test_assemble_collapses_same_id_across_feeds(cs_ai_xml, cs_cl_xml):
    requested = {"cs.AI": parse_feed(cs_ai_xml), "cs.CL": parse_feed(cs_cl_xml)}
    idx = build_announce_index(requested)
    recs = assemble(requested, idx)
    assert [r["id"] for r in recs].count("2605.15202v1") == 1

def test_write_jsonl_roundtrip(tmp_path, cs_ai_xml):
    requested = {"cs.AI": parse_feed(cs_ai_xml)}
    idx = build_announce_index(requested)
    recs = assemble(requested, idx)
    out = tmp_path / "2026-05-18.jsonl"
    write_jsonl(recs, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["id"] == "2605.15204v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_transform.py -v`
Expected: FAIL — `ImportError: cannot import name 'assemble'`

- [ ] **Step 3: Add implementation** — append to `daily_arxiv_rss/transform.py`

```python
import json
from pathlib import Path


def assemble(requested_feeds: dict[str, list[RawItem]],
             announce_index: dict[str, dict[str, str]]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for items in requested_feeds.values():
        for it in items:
            rec = to_record(it)
            if rec["id"] in seen:
                continue
            seen.add(rec["id"])
            rec["categories"] = resolved_categories(it, announce_index)
            out.append(rec)
    return out


def write_jsonl(records: list[dict], path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_transform.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add daily_arxiv_rss/transform.py tests/test_transform.py
git commit -m "feat: assembly dedup + JSONL writer"
```

---

## Task 5: Feeds — URL build, fetch, SOT (`feeds.py`)

**Files:**
- Create: `daily_arxiv_rss/feeds.py`
- Test: `tests/test_feeds.py`

`feed_url(cat)` → `https://rss.arxiv.org/rss/{cat}`. `sot_path(sot_dir, cat, yyyymmdd)` → `{sot_dir}/{cat}_{yyyymmdd}.xml`. `fetch(url, *, sleep, retries)` → bytes, with backoff on HTTP 429/503 (injectable `_opener` for tests). `save_sot(xml, path)` writes bytes.

- [ ] **Step 1: Write the failing test** — `tests/test_feeds.py`

```python
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

def test_fetch_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}
    class FakeResp:
        status = 200
        def read(self): return b"<rss/>"
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake_open(url, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            from urllib.error import HTTPError
            raise HTTPError(url, 429, "Too Many Requests", {}, None)
        return FakeResp()
    out = feeds.fetch("http://x", sleep=lambda s: None, retries=5, _opener=fake_open)
    assert out == b"<rss/>"
    assert calls["n"] == 3

def test_fetch_gives_up_after_retries(monkeypatch):
    from urllib.error import HTTPError
    def always_429(url, timeout=0):
        raise HTTPError(url, 429, "x", {}, None)
    with pytest.raises(HTTPError):
        feeds.fetch("http://x", sleep=lambda s: None, retries=2, _opener=always_429)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_feeds.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'daily_arxiv_rss.feeds'`

- [ ] **Step 3: Write implementation** — `daily_arxiv_rss/feeds.py`

```python
import time
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

BASE = "https://rss.arxiv.org/rss"
_RETRY_STATUS = {429, 503}


def feed_url(category: str) -> str:
    return f"{BASE}/{category}"


def sot_path(sot_dir: str, category: str, yyyymmdd: str) -> str:
    return f"{sot_dir}/{category}_{yyyymmdd}.xml"


def save_sot(xml_bytes: bytes, path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(xml_bytes)


def _default_opener(url: str, timeout: int = 30):
    return urllib.request.urlopen(url, timeout=timeout)


def fetch(url: str, *, sleep=time.sleep, retries: int = 5,
          base_delay: float = 3.0, _opener=_default_opener) -> bytes:
    attempt = 0
    while True:
        try:
            with _opener(url, timeout=30) as resp:
                return resp.read()
        except HTTPError as e:
            attempt += 1
            if e.code in _RETRY_STATUS and attempt < retries:
                sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_feeds.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add daily_arxiv_rss/feeds.py tests/test_feeds.py
git commit -m "feat: feed URL/SOT helpers + fetch with 429/503 backoff"
```

---

## Task 6: CLI orchestrator (`crawl.py`)

**Files:**
- Create: `daily_arxiv_rss/crawl.py`
- Test: `tests/test_crawl.py`

`run(categories, out_path, sot_dir, yyyymmdd, fetcher)`: (1) for each requested category fetch feed → save SOT → parse; (2) collect cross items' category union not yet fetched → fetch+SOT+parse those too; (3) build announce index over ALL parsed feeds; (4) `assemble` requested feeds; (5) `write_jsonl`. `fetcher(category) -> bytes` is injected (real default wraps `feeds.fetch`). CLI: `--out` (required), `--categories` (default env `CATEGORIES` or `cs.CV`), `--sot-dir` (default `data/rss`).

- [ ] **Step 1: Write the failing test** — `tests/test_crawl.py`

```python
import json
from daily_arxiv_rss import crawl

def test_run_endtoend_with_injected_fetcher(tmp_path, cs_ai_xml, cs_cl_xml):
    feeds_bytes = {"cs.AI": cs_ai_xml, "cs.CL": cs_cl_xml}
    fetched = []
    def fetcher(category):
        fetched.append(category)
        return feeds_bytes[category]
    out = tmp_path / "2026-05-18.jsonl"
    crawl.run(categories=["cs.AI"], out_path=str(out),
              sot_dir=str(tmp_path / "rss"), yyyymmdd="20260518",
              fetcher=fetcher)
    # cs.AI requested; cs.CL pulled in because of the cross item
    assert "cs.AI" in fetched and "cs.CL" in fetched
    # SOT written for both
    assert (tmp_path / "rss" / "cs.AI_20260518.xml").exists()
    assert (tmp_path / "rss" / "cs.CL_20260518.xml").exists()
    recs = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 3
    cross = [r for r in recs if r["id"] == "2605.15202v1"][0]
    assert cross["categories"][0] == "cs.CL"  # resolved via pulled cs.CL feed

def test_parse_args_defaults(monkeypatch):
    monkeypatch.setenv("CATEGORIES", "cs.AI, cs.CL")
    ns = crawl.parse_args(["--out", "data/x.jsonl"])
    assert ns.out == "data/x.jsonl"
    assert ns.categories == ["cs.AI", "cs.CL"]
    assert ns.sot_dir == "data/rss"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_crawl.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'daily_arxiv_rss.crawl'`

- [ ] **Step 3: Write implementation** — `daily_arxiv_rss/crawl.py`

```python
import argparse
import os
import sys
from datetime import datetime, timezone

from daily_arxiv_rss import feeds
from daily_arxiv_rss.parse import parse_feed
from daily_arxiv_rss.transform import build_announce_index, assemble, write_jsonl


def _default_fetcher(category: str) -> bytes:
    return feeds.fetch(feeds.feed_url(category))


def run(categories, out_path, sot_dir, yyyymmdd, fetcher=_default_fetcher):
    parsed: dict[str, list] = {}

    def pull(cat: str):
        if cat in parsed:
            return
        xml = fetcher(cat)
        feeds.save_sot(xml, feeds.sot_path(sot_dir, cat, yyyymmdd))
        parsed[cat] = parse_feed(xml)

    for cat in categories:
        pull(cat)

    requested = {c: parsed[c] for c in categories if c in parsed}

    extra: set[str] = set()
    for items in requested.values():
        for it in items:
            if it.announce_type == "cross":
                extra.update(it.categories)
    for cat in sorted(extra - set(parsed)):
        try:
            pull(cat)
        except Exception as e:  # primary-resolution feed is best-effort
            print(f"[warn] could not fetch feed {cat}: {e}", file=sys.stderr)

    announce_index = build_announce_index(parsed)
    records = assemble(requested, announce_index)
    write_jsonl(records, out_path)
    print(f"wrote {len(records)} records to {out_path}", file=sys.stderr)
    return records


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--categories",
                   default=os.environ.get("CATEGORIES", "cs.CV"))
    p.add_argument("--sot-dir", default="data/rss")
    ns = p.parse_args(argv)
    ns.categories = [c.strip() for c in ns.categories.split(",") if c.strip()]
    return ns


def main(argv=None):
    ns = parse_args(argv)
    yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")
    run(ns.categories, ns.out, ns.sot_dir, yyyymmdd)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_crawl.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -v`
Expected: PASS (all tasks 1–6 green)

- [ ] **Step 6: Commit**

```bash
git add daily_arxiv_rss/crawl.py tests/test_crawl.py
git commit -m "feat: crawl CLI orchestrator (fetch->SOT->transform->JSONL)"
```

---

## Task 7: Repoint `run.sh`

**Files:**
- Modify: `run.sh` (the crawl block and the dedup `cd`)

Current crawl block (verified): `cd daily_arxiv` then `scrapy crawl arxiv -o ../data/${today}.jsonl`; later `python daily_arxiv/check_stats.py` runs while cwd is `daily_arxiv/` so its `../data` resolves to repo `data/`. New crawler runs from repo root; the dedup must still run with cwd `daily_arxiv/`.

- [ ] **Step 1: Replace the crawl invocation**

Find in `run.sh`:

```bash
cd daily_arxiv
scrapy crawl arxiv -o ../data/${today}.jsonl

if [ ! -f "../data/${today}.jsonl" ]; then
```

Replace with:

```bash
uv run python -m daily_arxiv_rss.crawl --out "data/${today}.jsonl"

if [ ! -f "data/${today}.jsonl" ]; then
```

- [ ] **Step 2: Fix the dedup step cwd**

Find the dedup line in `run.sh`:

```bash
python daily_arxiv/check_stats.py
```

Replace with (run it with cwd = `daily_arxiv/` exactly as before, since it uses `../data`):

```bash
( cd daily_arxiv && python daily_arxiv/check_stats.py )
```

- [ ] **Step 3: Sanity-check the script parses**

Run: `bash -n run.sh`
Expected: no output, exit 0 (syntax OK).

- [ ] **Step 4: Commit**

```bash
git add run.sh
git commit -m "chore: repoint run.sh crawl step to daily_arxiv_rss"
```

---

## Task 8: Repoint `.github/workflows/run.yml`

**Files:**
- Modify: `.github/workflows/run.yml` (the "Crawl arXiv papers" step only)

The dedup step in run.yml is a SEPARATE step that already does its own `cd daily_arxiv` — leave it untouched.

- [ ] **Step 1: Replace the crawl command**

Find in the "Crawl arXiv papers" step:

```yaml
        cd daily_arxiv
        export OPENAI_API_KEY=${{ secrets.OPENAI_API_KEY }}
        export OPENAI_BASE_URL=${{ secrets.OPENAI_BASE_URL }}
        export TOKEN_GITHUB=${{ secrets.TOKEN_GITHUB }}
        export LANGUAGE="${{ vars.LANGUAGE }}"
        export CATEGORIES="${{ vars.CATEGORIES }}"
        export MODEL_NAME="${{ vars.MODEL_NAME }}"
        
        # 使用Scrapy爬取
        # Use Scrapy to crawl
        scrapy crawl arxiv -o ../data/${today}.jsonl
        
        # 检查爬取是否成功 / Check if crawling was successful
        if [ ! -f "../data/${today}.jsonl" ]; then
```

Replace with:

```yaml
        export CATEGORIES="${{ vars.CATEGORIES }}"

        # Use RSS-based crawler (daily_arxiv_rss)
        uv run python -m daily_arxiv_rss.crawl --out "data/${today}.jsonl"

        # 检查爬取是否成功 / Check if crawling was successful
        if [ ! -f "data/${today}.jsonl" ]; then
```

(The removed `OPENAI_*`/`LANGUAGE`/`MODEL_NAME` exports were unused by the crawl step; later steps set their own.)

- [ ] **Step 2: Validate YAML**

Run: `uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/run.yml')); print('ok')"`
Expected: `ok` (if PyYAML missing, run `uv run --with pyyaml python -c "..."` instead)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/run.yml
git commit -m "chore: repoint run.yml crawl step to daily_arxiv_rss"
```

---

## Task 9: Manual PDF downloader (`pdf.py`) — spec §11

**Files:**
- Create: `daily_arxiv_rss/pdf.py`
- Test: `tests/test_pdf.py`

`download_all(jsonl_path, out_dir, *, downloader, sleep, retries)`: read ids from the JSONL (`id` field, versioned); for each, target `{out_dir}/{id}.pdf`; skip if exists; call injected `downloader(arxiv_id, dest)`; backoff on exception; per-file failure non-fatal. Default downloader uses batched `arxiv.Search(id_list=...)` + `Result.download_pdf`. CLI: `--data` (required JSONL), `--out-dir` (default `pdfs`).

- [ ] **Step 1: Write the failing test** — `tests/test_pdf.py`

```python
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
    assert called == ["2605.15202v1"]               # skipped the existing one
    assert (out / "2605.15202v1.pdf").read_bytes() == b"%PDF new"

def test_download_all_failure_is_non_fatal(tmp_path):
    data = tmp_path / "d.jsonl"
    _write_jsonl(data, ["2605.0001v1", "2605.0002v1"])
    out = tmp_path / "pdfs"; out.mkdir()
    def downloader(arxiv_id, dest):
        if arxiv_id == "2605.0001v1":
            raise RuntimeError("boom")
        open(dest, "wb").write(b"ok")
    summary = pdf.download_all(str(data), str(out), downloader=downloader,
                               sleep=lambda s: None, retries=1)
    assert summary["ok"] == 1 and summary["failed"] == 1
    assert (out / "2605.0002v1.pdf").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pdf.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'daily_arxiv_rss.pdf'`

- [ ] **Step 3: Write implementation** — `daily_arxiv_rss/pdf.py`

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pdf.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add daily_arxiv_rss/pdf.py tests/test_pdf.py
git commit -m "feat: manual PDF downloader (spec §11)"
```

---

## Task 10: Full suite + spec coverage check

- [ ] **Step 1: Run the entire suite**

Run: `uv run pytest -v`
Expected: PASS — all tests across parse/transform/feeds/crawl/pdf.

- [ ] **Step 2: Smoke the crawl CLI offline help**

Run: `uv run python -m daily_arxiv_rss.crawl --help`
Expected: argparse usage printed, exit 0.

- [ ] **Step 3: Update CLAUDE.md crawl section**

In `CLAUDE.md`, update the pipeline/architecture description so the crawl stage points to `daily_arxiv_rss` (RSS + SOT) instead of Scrapy, noting `daily_arxiv/` is retained but no longer invoked, and `id` is now versioned. Keep it concise (a few edited lines, not a rewrite).

- [ ] **Step 4: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for RSS crawl architecture"
```

---

## Self-Review (completed during planning)

- **Spec coverage:** §2 contract (Tasks 2,4 — exact 8 fields, versioned id, comment None, JSONL UTF-8); §4.2 two units (Tasks 5 fetch/SOT, 2–4 transform); §4.3 mapping incl. summary-prefix strip + author split (Task 2); §4.4 cross-primary closed-set algo + fallback (Task 3); §4.5 SOT path/persistence (Task 5, Task 6 writes under `data/rss/` so existing workflow carries it to the data branch); §5 versioned id + no new field (Task 2 asserts exact 8 keys); §8 only run.sh/run.yml changed (Tasks 7,8) + .gitignore (Task 0); §10 deterministic fixture tests + mocked fetch (all tasks); §11 PDF tool (Task 9). No uncovered requirement.
- **Placeholder scan:** every code/test step contains complete code; commands have expected output. None found.
- **Type consistency:** `RawItem` fields used identically across parse/transform; `to_record`/`resolved_categories`/`build_announce_index`/`assemble`/`write_jsonl`/`feeds.fetch`/`crawl.run` signatures consistent across tasks and tests.
- **Known residuals (from spec, not plan defects):** weekend RSS behavior + cross-primary fallback frequency remain post-cutover empirical items (spec §6/§9); not blockers.
