---
name: daily-digest
description: Use when the user wants to generate and publish the day's arXiv science-pop digest. Runs the full pipeline (crawl → dedup → download PDFs → write a full zh-Hant article + figure for EVERY paper → manifest → commit → push so GitHub Pages redeploys). Human-triggered, agent-executed, resumable.
---

# Daily Sci-Pop Digest

You produce one science-pop article per arXiv paper for the day and publish the site.
Design ref: `docs/superpowers/specs/2026-05-19-daily-digest-deploy-design.md`.
Run everything from the repo root. The user has ample token quota — quality over speed.

## FIRST: read POLICY.md

Read `.claude/skills/daily-digest/POLICY.md` before doing anything. It is the
user-owned steering file. **Where POLICY.md and this SKILL differ, POLICY.md
wins** (style, scope, length, structure, tone). This SKILL only describes the
mechanism; POLICY.md describes what the user wants.

## Hard rules

- **No filtering, no triage.** Every paper from the crawl (all categories the
  crawler returns, both `announce_type` `new` AND `cross`) gets a **full**
  article. There is no "short note" tier.
- **Resumable.** Before writing an article, if `data/articles/<id>.md` already
  exists, SKIP that paper. Re-running continues where you stopped. A full day
  is ~500+ papers and **will** hit the Claude 5-hour usage cap mid-run — that
  is expected; the user just re-runs `/daily-digest` and it continues.
- **One paper at a time per subagent; skip just the bad one.** If a single
  paper's text trips a content/usage-policy refusal, skip ONLY that paper
  (report `skipped (content)`) and continue — never let one paper abort a
  batch. Describe sensitive research (deepfake/adversarial/privacy) neutrally;
  these are legitimate published papers.
- **Figure captions must match the image you actually saw.** Never invent a
  caption. If a paper has no usable raster/diagram figure, omit the image and
  say so in the text — do not fabricate.
- **No PDF → skip honestly.** Some papers' PDFs are unobtainable (arXiv serves
  0 bytes, or persistent HTTP 429). Skip and list them; never fabricate from
  the abstract alone. ~4/day is normal.
- Do not touch `daily_arxiv/`. Do not commit `pdfs/`, `data/*.jsonl`,
  `data/rss/` (gitignored).

## Procedure (state-aware: any phase can be entered any time)

The pipeline is restartable from any state. A fresh Claude invoking
`/daily-digest` doesn't need to know what was already done — read the
current state, decide, do.

### 0. Read pipeline state
```bash
uv run python -m daily_arxiv_rss.status
```
Returns a JSON snapshot with the **decision** field:
- `all_done` — every wanted id has an article. Maybe still probe (step 1)
  for fresh arXiv content; if crawl no-ops, truly STOP.
- `write_articles` — articles missing for ids whose PDF is already on disk.
  Go straight to step 3 (wave loop).
- `start_pdf` — PDFs missing and no pdf daemon running. Step 2 to launch
  one in background, then step 3 (concurrent with the daemon).
- `wait_for_pdfs` — pdf daemon already running, no articles eligible right
  now. Step 3's wave loop polls and waits.
- `crawl_then_recheck` (implicit) — always also do step 1 unless you just did.

### 1. Crawl (probe → early-exit-or-full-crawl → per-pubDate merge)
```bash
uv run python -m daily_arxiv_rss.crawl
```
Exit code: `0` = new ids added, `1` = no-op (probe unchanged), `2` = error.

**no-op (1) does NOT stop the pipeline** — it just means "no new ids from
arXiv this run"; there might still be PDFs to download or articles to write
from prior runs. Continue to step 0/2/3 based on the snapshot's decision.

Each paper is filed under **its own RSS-item pubDate** into
`data/<pub_date>.jsonl` (append-only-by-id). SOTs land at
`data/rss/<cat>_<fetched-at>.xml` (immutable). Journal entry recorded.

### 2. Start PDF downloader (only if snapshot said `start_pdf`)
```bash
nohup uv run python -m daily_arxiv_rss.pdf \
  > /tmp/daily-digest-pdf.log 2>&1 &
disown
```
The pdf module is self-contained: it derives **wanted** from
`data/*.jsonl`, **have** from `pdfs/<id>.pdf` size>0, and only persists
**cool-downs** in `.state/rss/pdf-failures.json`. A `.state/rss/pdf.pid`
lock prevents two from running at once. **The skill never starts a second
pdf daemon** — the snapshot tells you when one is already alive.

Default 15s/req per `arxiv.org/robots.txt` Crawl-delay. Don't override.

### 3. Wave loop with patience (writes articles concurrent with PDF daemon)

A day is too large to do serially, AND PDFs may still be arriving. Loop:

```
LOOP:
  uv run python -m daily_arxiv_rss.wave --wave 100 --per 10
  if picked > 0:
      dispatch parallel subagents (one per agent-NN.jsonl)
      wait for ALL agents to finish
      uv run python -m daily_arxiv_rss.manifest   # step 4
      step-5 commit + push                          # incremental deploy
      continue LOOP
  else:
      uv run python -m daily_arxiv_rss.status      # refresh
      if decision == "all_done": break
      if decision == "wait_for_pdfs":
          sleep 60s ; continue LOOP                 # let pdf daemon catch up
      if decision == "start_pdf":
          restart step 2 (daemon died) ; continue LOOP
      else (only unobtainable ids left): break
```

Each subagent gets its `agent-NN.jsonl` worklist — papers whose PDF is on
disk (size>0, mtime older than ~8s) and have no article yet, newest arXiv
id first. Dispatch in parallel (general-purpose agents; ~10/wave).

**Each subagent** is given its `agent-NN.jsonl` and these instructions:
process every record IN ORDER, ONE AT A TIME (fully finish one before the
next, so a content-block on one paper can't lose the others); for each
`id` (versioned, e.g. `2605.15202v1`; `arxiv_id` = id without `vN`):
- if `data/articles/<id>.md` exists → skip (`skipped (exists)`)
- if `pdfs/<id>.pdf` missing → skip (`skipped (no pdf)`); do NOT download
- if its text trips a refusal → skip ONLY it (`skipped (content)`), continue
- else do a–d below, then report `<id>: done (fig: yes/no)`.
The subagent writes ONLY `data/articles/<id>.md` and
`assets/articles/<id>-fig1.webp` for its ids — no git, no manifest, no jsonl.

a. Extract text:
```bash
uv run --with pypdf python - <<'PY'
from pypdf import PdfReader
import sys
r=PdfReader(f"pdfs/{sys.argv[1]}.pdf")
open(f"/tmp/{sys.argv[1]}.txt","w",encoding="utf-8",errors="replace").write(
  "\n".join((p.extract_text() or "") for p in r.pages))
PY
```
(pass the id as the arg) Then Read `/tmp/<id>.txt` — abstract, intro, method,
results, limitations, conclusion.

b. Render candidate pages and **look at them**:
```bash
uv run --with pymupdf python - <<'PY'
import fitz,sys
d=fitz.open(f"pdfs/{sys.argv[1]}.pdf")
for n in range(min(8,d.page_count)):
    d[n].get_pixmap(matrix=fitz.Matrix(2,2)).save(f"/tmp/{sys.argv[1]}-p{n+1}.png")
PY
```
Use the Read tool to view the rendered pages. Pick the single most
explanatory real figure (a diagram or key plot — not equations/tables/logos).
If the figure is in the appendix, render those pages too.

c. Crop it tight and convert to size-tuned webp:
```bash
uv run --with pillow python - <<'PY'
from PIL import Image; import sys
src,dst,x0,y0,x1,y1,maxw,q=sys.argv[1:9]
im=Image.open(src).convert("RGB"); W,H=im.size
im=im.crop((int(float(x0)*W),int(float(y0)*H),int(float(x1)*W),int(float(y1)*H)))
w,h=im.size; mw=int(maxw)
if w>mw: im=im.resize((mw,round(h*mw/w)), Image.LANCZOS)
im.save(dst,"WEBP",quality=int(q),method=6)
print(im.size)
PY
```
e.g. args: `/tmp/<id>-p2.png assets/articles/<id>-fig1.webp 0.06 0.05 0.97 0.33 980 80`
Re-view the cropped webp to confirm it's right; re-crop if off. Tune `maxw`/`q`
per image so it's the smallest that stays legible (simple line charts → smaller).

d. Write `data/articles/<id>.md` per the **Style guide** below.

### 4. Manifest + index
```bash
uv run python -m daily_arxiv_rss.manifest
```
Rebuilds **every** `data/articles/<pub_date>.json` from every
`data/articles/*.md`, grouping each article by **its own paper's pub_date**
(read from `data/<pub_date>.jsonl`). Hand-written seed entries not in any
jsonl are preserved verbatim. `data/articles/index.json` is regenerated
with all dates newest-first. Run after every wave (idempotent).

### 5. Publish
```bash
test -f .nojekyll || touch .nojekyll          # REQUIRED: Pages is Jekyll-built;
# without .nojekyll, Jekyll strips every data/articles/*.md → 404 online.
# Never re-add _config.yml. Never enable .github/workflows/run.yml.
git add .nojekyll data/articles/index.json data/articles/*.json \
        data/articles/*.md assets/articles/*.webp
git commit -m "digest: $(date -u +%Y-%m-%d) (N articles)"
git push origin main
```
GitHub Pages redeploys automatically (CDN+browser cache the JSON hard — tell
the user to hard-refresh, Ctrl+Shift+R). Tell the user the live URL
`https://<owner>.github.io/<repo>/` (the calendar shows every date that has
articles) and the per-pubDate counts from step 4.

## Style guide (every article .md)

Traditional Chinese, science-pop, for non-researchers. Structure (from
`001-news/run-04`):

1. `# <催眼吸睛的中文標題>` — rewritten for a layperson, NOT the paper title.
   This first line is the big title and the news-card headline.
2. A metadata block:
   ```
   > 原始論文：<English title>
   > 作者·單位：<authors（單位）>
   > arXiv：<id> ・ 分類：<category_label>
   ```
3. `一句話說重點：<one vivid sentence>` then `---`. This sentence is also the
   card `hook`.
4. Plain-language sections with analogies: 背景/問題 → 怎麼做 → 結果 →
   做不到的地方. Use everyday metaphors; expand every acronym once.
5. A figure section: `![<caption matching the image>](assets/articles/<id>-fig1.webp)`
   followed by a paragraph explaining what the figure shows (axes, what the
   lines/boxes mean, the takeaway). Caption MUST match what you saw.
6. `## 想自己判斷這篇可不可信？` — a markdown table: 訊號 | 這篇的情況 | 怎麼解讀
   (作者/單位、是否預印本未同儕審查、證據強度、用詞保守度、有無公開程式碼…).
7. `## 怎麼看這件事` — 為什麼在意 / 哪裡該保留懷疑 / 怎麼理解這個方向.

Tone: concrete, honest about limitations, no hype. Use `**bold**` sparingly
(the site renders one bold weight, no color). Image paths are repo-root
relative with NO leading slash (`assets/articles/...`).

## Notes
- The **Style guide** above is the default; **POLICY.md overrides it**. Pass
  the relevant POLICY.md points into each subagent's instructions.
- A day is large (~500+); expect to hit the 5-hour quota mid-run. Just re-run
  `/daily-digest` later — the wave loop + skip-if-exists resumes automatically.
- "Rewrite an already-published day with new POLICY": `rm` that day's
  `data/articles/*.md` (keep hand-written seeds), then run the wave loop again.
- Examples to match in voice/length: `data/articles/2605.15217v1.md`,
  `2605.15205v1.md`, `2605.15219v1.md`.
