# Crawl Step Virtualization via RSS — Design Spec

Date: 2026-05-19
Status: Approved (2026-05-19) — proceeding to implementation plan
Scope: (1) Replace the Scrapy-based crawl step with an RSS-based implementation behind a stable contract, without breaking the fork's existing interface. (2) Add a separate, manual, local-only PDF downloader for offline AI-agent analysis.

## 1. Context & Goal

This repo is a fork of `dw-dengwei/daily-arXiv-ai-enhanced`. The crawl step (Scrapy project under `daily_arxiv/`) currently:

- Scrapes `arxiv.org/list/{cat}/new` HTML for paper IDs (the only genuine "must crawl" part).
- Enriches each ID one-by-one via the official `arxiv` API client in the Scrapy pipeline.

Observed problem (verified from live logs): the per-paper `arxiv` API calls to `export.arxiv.org/api/query` get rate-limited (HTTP 429/503) relentlessly — hundreds of sequential requests, ~1 item/min. The HTML scrape itself returns 200 fine; the 429 is entirely the per-paper API enrichment (`pipelines.py:26`).

**Goal:** Virtualize the crawl step behind a stable input/output contract. Implementation becomes a parallel, swappable module. Do not modify `daily_arxiv/`. Only `run.sh` and `.github/workflows/run.yml` change to point at the new implementation.

**Secondary goal (separate concern):** Provide a manual, local-only tool to download each day's PDFs so the user can hand-feed them to an AI agent for analysis. This is NOT part of the automated daily pipeline, NOT wired into `run.sh`/`run.yml`/GitHub Actions, and PDFs are NOT committed to git. It consumes the crawl step's output (the produced JSONL id list). Specified in §11.

**Guiding principle (user):** This is someone else's project. Characterize and preserve the existing interface; do not break upstream contracts. Keep the JSONL output schema exactly as-is.

## 2. The Current De-Facto Contract (MUST NOT BREAK)

The crawl step's existing interface, derived from `spiders/arxiv.py`, `pipelines.py`, `run.sh`, `run.yml`, and downstream consumers:

### 2.1 Invocation contract
- Caller computes `today = date -u "+%Y-%m-%d"` (UTC).
- Caller deletes any pre-existing `data/{today}.jsonl` first (producer must yield a fresh file).
- Caller invokes the crawl step, which writes a JSONL to a caller-specified path (`data/{today}.jsonl`).
- Success criterion is purely: **the output file exists**. (`if [ ! -f ... ]` → failure.) Per-item errors do not fail the step.

### 2.2 Input contract
- `CATEGORIES` environment variable: comma-separated arXiv categories, e.g. `"cs.AI, cs.CL"`. Stripped of whitespace. Default `cs.CV` if unset.
- Network access to arXiv. No other real inputs. (Date is NOT a crawler input today — it only names the output file.)

### 2.3 Output contract — JSONL, UTF-8, one JSON object per line, exactly these fields
| Field | Type | Notes |
|-------|------|-------|
| `id` | str | arXiv id — **currently bare/version-less** (e.g. `2605.15202`), produced by the old spider via the abstract link. §5 deliberately changes this to versioned. |
| `categories` | list[str] | `categories[0]` is treated by `to_md/convert.py` as the **primary** (website grouping) |
| `pdf` | str | `https://arxiv.org/pdf/{bare-id}` |
| `abs` | str | `https://arxiv.org/abs/{bare-id}` |
| `authors` | list[str] | author display names |
| `title` | str | |
| `comment` | str \| None | arXiv author comment; **no consumer reads it** (verified) |
| `summary` | str | abstract text; used by AI stage and website |

- Duplicate `id` lines are tolerated downstream (`enhance.py` and `check_stats.py` both dedupe).
- Ordering is not significant.

### 2.4 Downstream consumers (who breaks if the contract breaks)
- `daily_arxiv/daily_arxiv/check_stats.py` (stage 2 dedup): keys on `id`, intersects today's ids with the **previous 7 days'** ids.
- `ai/enhance.py` (stage 3): reads jsonl; needs `id`, `summary`; dedupes by `id`.
- `to_md/convert.py` (stage 4): needs `categories[0]`, `title`, `authors`, `summary`, `abs`.
- Frontend (via `data` branch jsonl, post-AI): uses `id` as DOM/data identity; `abs`/`pdf`, `title`, `authors`, `summary`, AI fields.
- `run.sh` / `run.yml`: depend on invocation convention and filename `data/{YYYY-MM-DD}.jsonl`.

## 3. Constraints

- Do not modify anything under `daily_arxiv/` (leave the Scrapy project intact for upstream-trackability).
- Only `run.sh` and `.github/workflows/run.yml` may change to repoint the crawl step.
- New code lives in a new top-level module folder: **`daily_arxiv_rss/`**.
- JSONL output schema stays exactly the 8 fields above — no added/removed fields.
- No history dedup inside the crawler (that remains `check_stats.py`'s job, unchanged).

## 4. Chosen Approach: RSS feeds + stored SOT + transform

### 4.1 Why RSS (vs alternatives, briefly)
- **Per-paper `arxiv` API** (status quo): causes the 429 problem. Rejected.
- **API `cat:X AND submittedDate:[range]`**: kills 429 but changes "today's papers" from *announced* to *submitted* (per-day count/composition diverges from upstream; weekend batching edge cases). Rejected for fidelity.
- **arXiv per-category RSS** (`https://rss.arxiv.org/rss/{category}`): preserves *announced* semantics (matches upstream exactly), structured XML (no fragile HTML CSS selectors), one request per category (kills 429 — feed already contains title/authors/abstract/categories), and exposes `announce_type` (new/cross/replace). **Chosen.**

### 4.2 Architecture — two units with a clear boundary

**Unit A — Fetch layer (RSS → SOT)**
- For each category in `CATEGORIES`, GET `https://rss.arxiv.org/rss/{category}`.
- Additionally, collect the union of distinct categories appearing on any `announce_type=cross` item in the fetched feeds, and fetch those feeds too (needed for primary resolution — see 4.4).
- Store each fetched feed verbatim to the SOT: **`data/rss/{category}_YYYYMMDD.xml`** (`YYYYMMDD` = UTC date matching the run).
- Fetch is the only network activity. One request per distinct category. No per-paper calls.

**Unit B — Transform layer (SOT → JSONL)**
- Reads the stored SOT XML files (pure, offline, replayable — enables deterministic unit tests).
- Parses items, applies the field mapping (4.3) and cross-primary resolution (4.4).
- Within a run, collapse identical `id` values that appear across multiple requested feeds (same paper listed in two requested categories) — keep one. (This is run-local assembly dedup, NOT cross-day dedup.)
- Writes the 8-field JSONL to the caller-specified output path.

This separation means the transform can be re-run against stored SOT without re-fetching, and is independently testable.

### 4.3 RSS → contract field mapping
| Contract field | RSS source | Transformation |
|----------------|-----------|----------------|
| `id` | `<guid>` | strip `oai:arXiv.org:` prefix → keep **versioned** id, e.g. `2605.15202v1` |
| `abs` | `<link>` | direct (already bare-form abs URL) |
| `pdf` | derived | `https://arxiv.org/pdf/{bare-id}` (bare id = guid id with `vN` stripped, used **only** to build URLs) |
| `title` | `<title>` | direct |
| `summary` | `<description>` | strip leading `arXiv:<id> Announce Type: <type> \nAbstract: ` prefix; take text after first `Abstract: ` |
| `categories` | all `<category>` | collect in order, then reorder per 4.4 so primary is `categories[0]` |
| `authors` | `<dc:creator>` | split on `", "` into `list[str]` (contract requires list; `convert.py` does `",".join`) |
| `comment` | (absent in RSS) | always `None` — verified inert (no consumer reads `comment`) |

Note: `id` is the only field whose string value changes vs. the old output (now versioned). `abs`/`pdf` stay bare to minimize format drift.

### 4.4 Cross-list primary resolution (RSS-only, no per-paper API)
RSS orders `<category>` with the **feed's category first**, NOT the primary (verified empirically: a `cross` item in the cs.AI feed listed `cs.AI` first though its primary was elsewhere). Upstream's `categories[0]` is the true primary (it came from the Atom API). To stay at parity:

Algorithm (closed set — a paper's primary is always among its own listed categories):
1. Fetch the cs.AI-style requested feeds.
2. For each `announce_type=cross` item, note its listed `<category>` set.
3. Fetch the feeds for the union of those categories (Unit A, into SOT).
4. For each cross item, find which of its categories' feeds lists the same `guid` with `announce_type=new`. That category is the primary → reorder `categories` so it is `categories[0]`.
5. **Fallback** (primary feed unavailable / paper not found as `new` in any fetched feed / timing mismatch): keep RSS order as-is and log. Do not chase 100%.

### 4.5 SOT (Source of Truth)
- Path: `data/rss/{category}_YYYYMMDD.xml`, raw feed bytes.
- Auto-persists to the `data` branch via existing workflow logic (`cp -r data/*` → data branch); excluded from `main` (`git reset -- data/*`); not matched by `assets/file-list.txt` glob (`ls data/*.jsonl`, non-recursive). **No workflow change needed for SOT to persist correctly.**
- Purpose: provenance, reprocessability (re-derive JSONL if transform logic changes), offline deterministic testing, local cross-primary join without extra network.
- Cost: small (tens of KB per category per day) relative to existing `data` branch contents.

## 5. id Decision & Consequences (explicitly accepted)

- `id` = **versioned** (from `<guid>`). No new `arxiv_base_id` field — schema stays exactly 8 fields.
- Rationale: v1 and v2 are genuinely different releases; the user wants them preserved, not collapsed. A versioned `id` makes `check_stats.py` (unchanged) treat v1 and v2 as distinct papers automatically, while still deduping exact same-version repeats across cron reruns.
- **Accepted trade-off:** historical `data` branch ids are bare. Versioned ids will not match them. For the ≤7-day `check_stats.py` lookback window after cutover, already-processed papers may be re-processed once. Bounded, non-destructive, self-heals after the window rolls to all-versioned files.
- Information is not lost: bare id is derivable from versioned (`strip vN`) at any future time. Versioned is the superset.

## 6. Known Risks & Accepted Trade-offs
- **Announced vs submitted:** RSS = announced semantics = parity with upstream. No regression.
- **Weekend RSS behavior — UNVERIFIED:** arXiv announces Sun–Thu only (documented). Whether the RSS feed is empty/unchanged on Fri/Sat is NOT documented and not yet empirically observed. **Not a blocker:** `check_stats.py`'s "no new content / duplicate → skip" path absorbs empty or repeated feeds regardless. Listed as a post-cutover empirical verification item.
- **Cross-primary fallback:** rare cross items whose primary feed isn't fetched keep RSS order; `categories[0]` may be the feed category instead of true primary for those. Logged. Frequency to be observed.
- **Cutover transition window:** see §5 (≤7-day bounded re-processing).

## 7. Out of Scope (deferred)
- Replacement (`announce_type=replace`) handling — feed exposes it; policy deferred.
- Relocating/refactoring `check_stats.py` or changing its dedup key.
- Removing `scrapy` from `pyproject.toml` / deleting `daily_arxiv/` (kept intact for now).
- Any change to AI/markdown/website stages.
- Historical PDF backfill (the PDF tool §11 covers only the current run's papers).
- Automating/scheduling the PDF tool (it stays manual by design).

## 8. Integration Changes (the entire blast radius)
- New module folder `daily_arxiv_rss/` (new code only).
- `run.sh`: replace the `cd daily_arxiv` + `scrapy crawl arxiv -o ../data/${today}.jsonl` block with an invocation of the new module producing the same `data/${today}.jsonl`.
- `.github/workflows/run.yml`: same replacement in the "Crawl arXiv papers" step.
- `daily_arxiv/` untouched. Downstream stages untouched. Output schema unchanged (except `id` now versioned, by decision §5).
- New `.gitignore` entry for the local PDF directory (§11). `run.sh`/`run.yml`/Actions are NOT changed for the PDF tool — it is invoked manually and separately.

## 9. Open / To-Verify Items
1. Module folder is `daily_arxiv_rss/` (decided). Invocation: `--categories` from `CATEGORIES` env (default `cs.CV`); `--sot-dir` default `data/rss`; `--out` is **optional** — when omitted it defaults to `data/<feed pubDate>.jsonl` (the RSS announcement date, RFC822 `pubDate` → `YYYY-MM-DD`; falls back to UTC date only if no pubDate parseable). **The automated pipeline (`run.sh`/`run.yml`) keeps passing explicit `--out "data/${today}.jsonl"`** because downstream steps (`check_stats`, AI, convert, the pre-delete, `crawl_date` output) all key off that same UTC `${today}`; the feed-date default is a manual/local convenience only.
2. Weekend RSS feed content (empirical, post-cutover).
3. Cross-primary fallback frequency (empirical).
4. Confirm RSS `<category>` ordering for `new` items is reliably primary-first (parity assumption; matches upstream's existing assumption).

## 10. Testing Approach
- SOT enables deterministic tests: stored RSS XML fixtures → Transform layer → assert exact 8-field JSONL output (including versioned id, comment=None, author list split, summary prefix stripped, cross-primary reordering).
- Fetch layer tested separately (feed URL construction, cross-category union collection) with mocked HTTP.
- PDF tool (§11): skip-existing logic and backoff/retry tested with mocked download; no live arXiv calls in tests.

## 11. Manual PDF Downloader (separate, local-only)

A standalone, manually-run tool. Not part of the automated pipeline; not in CI; PDFs never committed.

### 11.1 Input
- The current run's `data/{date}.jsonl` (canonical post-transform id list, versioned ids). The tool reads ids from there. No re-fetch of the listing.

### 11.2 Behavior
- Obtain `arxiv` `Result` objects via **batched** `arxiv.Search(id_list=[...])` (id_list holds many ids per request → few API calls, polite `arxiv.Client`), then call `Result.download_pdf(dirpath, filename)` per paper.
- **Honest caveat:** the `arxiv` client's `delay_seconds`/`num_retries` apply only to the API *query* pagination. `Result.download_pdf()` is a bare `urlretrieve` with **no throttle or retry on the PDF download itself**. The tool therefore wraps downloads with its own: sequential (no concurrency), sleep between files, exponential backoff on HTTP 429/503, per-file failure is non-fatal (log and continue).
- **Idempotent / resumable:** skip any paper whose target file already exists. Safe to re-run.

### 11.3 Output
- Local directory (e.g. `pdfs/`), git-ignored. One file per paper named by **versioned id**: `pdfs/{versioned-id}.pdf` (e.g. `pdfs/2605.15202v1.pdf`) — consistent with §5 so each version is kept separately and the AI agent can map id → file.

### 11.4 Scope limits
- Only the current run's papers (no historical backfill — §7).
- Volume is one category-day (tens to low hundreds); acceptable for a manual gentle run. If volume ever grows beyond gentle single-host fetching, the ToS-compliant path is arXiv bulk data (S3/Kaggle/GCS) — explicitly out of scope here.

### 11.5 Open items
- Exact CLI signature (input JSONL path, output dir, pacing/backoff parameters) — fixed in the implementation plan.
- Per-file inter-download delay value — tuned conservatively in the plan; arXiv has no published per-file PDF rate limit, so err gentle.
