# Daily Sci-Pop Digest — Deployment & One-Command Skill — Design Spec

Date: 2026-05-19
Status: Approved with corrections (user, 2026-05-19): NO triage, NO cs.AI filter — every crawled paper gets a full article; date UI mirrors the upstream author's flatpickr calendar; article reading UI unchanged; user has ample token quota; ship then iterate.
Scope: How the article site is published, and the single Claude Code skill the user runs each morning that does everything end-to-end.

## 1. Goal & constraints

- Every morning the user opens Claude Code and runs **one skill**; it crawls, dedups, picks, fetches PDFs, writes the science-pop articles + figures, updates the site, commits and pushes. GitHub Pages then serves it.
- AI writing uses the user's **Claude Code subscription** (the agent itself writes), not the paid API. So this is **human-triggered, agent-executed, one command** — NOT an unattended 6am cron (that would need paid API or headless scheduling, explicitly out of scope).
- Decisions locked by user: ① process **all of that day's cs.AI**; ② work merged to **`main`**; ③ `git push` already works (CLI authenticated, repo is the user's).

## 2. Process EVERYTHING — no triage, no filter (corrected by user)

Every paper the crawler returns gets a **full** run-04-style article — regardless of `announce_type` (`new` AND `cross`) and regardless of category (NO cs.AI-only filter; whatever the crawler's `CATEGORIES` yields). No short-note tier. The user has ample Claude Code quota and explicitly does not want triage.

Consequence the design must handle: a day is large, so the skill is **resumable** — skip any paper whose `data/articles/<id>.md` already exists, so re-running continues where a previous run stopped (quota/interruption).

## 3. Publishing model (GitHub Pages, decision ②/③)

- Everything is static and same-origin: `index.html` + `data/articles/**` + `assets/articles/**`, all relative paths → **GitHub Pages from `main` /(root)** serves it with zero rewriting. (Verified: project-Pages subpath works because all paths are relative.)
- One-time manual setup (not part of the daily skill): repo → Settings → Pages → Deploy from a branch → `main` / `/(root)`.
- Daily deploy = `git push origin main`; Pages redeploys automatically. No build step (static + `marked` via CDN).
- The old upstream machinery (`app.js`, `data-config.js`, `data` branch, `index-legacy.html`) is unused by the new site and left untouched.

## 4. Date-aware viewer (REQUIRED gap to close)

Today `index.html` hardcodes `./data/articles/2026-05-19.json`. For daily use it must become date-aware. Design:

- `data/articles/index.json` — `{ "dates": ["2026-05-19", ...] }`, **newest first**; the skill prepends today.
- `data/articles/<date>.json` — per-day manifest (current shape; metadata + `md` path; no body).
- `data/articles/<id>.md`, `assets/articles/<id>-fig1.webp` — per article.
- `index.html` behavior — **mirror the upstream author's date UX** (`index-legacy.html`/`app.js`): a calendar (the same lib upstream uses, **flatpickr** via CDN) behind a date button + a "currentDate" display; only dates present in `index.json` are enabled; default to the **latest** date. The existing card/article/prev-next reading UI is **unchanged** (decision ⑤ "介面完全不變" — we only add the calendar on top).
  - Selecting a date loads that day's `<date>.json` manifest and re-renders cards.
  - Deep link hash = `#<date>/<arxiv_id>` (shareable, static). Bare `#<arxiv_id>` → latest date.
  - Fixed prev/next stays within the selected day's list (newest→oldest).
- Backward compatible: existing `2026-05-19.json` already conforms; we add `index.json` + the flatpickr calendar.

## 5. The one-command skill

A project Claude Code skill at `.claude/skills/daily-digest/SKILL.md`, invoked as `/daily-digest`. It orchestrates (Python tools do the deterministic parts; the agent does the writing):

1. `python -m daily_arxiv_rss.crawl` → `data/<feed-date>.jsonl` (RSS, free).
2. `python -m daily_arxiv_rss.dedup --data <that file>` → trim + gate; if "no new content" → stop cleanly.
3. **No filter** — the day's worklist is *every* paper from step 2 (all categories, all announce types).
4. `python -m daily_arxiv_rss.pdf --data <worklist> --out-dir pdfs` (gentle, gitignored).
5. **Agent loop, per paper (resumable — skip if `data/articles/<id>.md` exists):** read PDF text (pypdf) + render candidate pages (PyMuPDF) → the agent *views* the rendered pages, picks the one real figure, crops it, converts to size-tuned `.webp`; writes `data/articles/<id>.md` (always a **full** article per §2) with `# headline` first line and the figure + a caption that matches what the agent actually saw; appends the per-day manifest entry.
6. Write/refresh `data/articles/<date>.json` and prepend the date to `data/articles/index.json`.
7. `git add` the article md/json/webp (+ `index.html` if changed) → `git commit` → `git push origin main`. Pages redeploys.

The skill body includes the **style guide** (run-04 structure, tone, the credibility table, figure-caption-must-match-image rule) and the exact schema, so output is consistent run-to-run. This is the durable artifact that makes the "one skill" reproducible.

## 6. Known risks / honest caveats

- **Figure step is the least deterministic.** Mitigation: the agent renders pages with PyMuPDF and *visually inspects* them (Claude Code can read images) to pick & crop — reliable but token-costing. Papers with only vector figures and no good raster: caption-only, no image, noted (acceptable per run-04 precedent).
- **Quota/time.** Full cs.AI/day is large even with triage; a run may hit the 5h limit. The skill must be **resumable**: skip papers whose `data/articles/<id>.md` already exists, so re-running continues where it stopped.
- **Volume in git.** Daily md (+ small webp) accumulate on `main`. Text + ~10–50KB webp/day is fine for years; revisit only if it balloons.
- **CDN dependency.** `marked` loads from jsdelivr; fine for a public site, breaks only offline. Vendoring locally is a future option.
- This skill is **triggered by the user**, runs while Claude Code is open; it is not a background scheduler.

## 7. Out of scope (for now)

- Unattended/scheduled runs (needs paid API or headless agent).
- Search, tags, pagination, RSS/Atom output, custom domain.
- Reworking/removing the old upstream UI files.
- Touching `daily_arxiv/` (still untouched; `check_stats.py` remains dead code).

## 8. Deliverables when built

1. Date-aware `index.html` + `data/articles/index.json` (§4).
2. `.claude/skills/daily-digest/SKILL.md` (§5) with embedded style guide + schema.
3. Updated `NOTES-articles.md` / `CLAUDE.md` pointer.
4. One-time Pages setting documented (user action).
