---
name: daily-digest
description: Use when the user wants to generate and publish the day's arXiv science-pop digest. Runs the full pipeline (crawl → dedup → download PDFs → write a full zh-Hant article + figure for EVERY paper → manifest → commit → push so GitHub Pages redeploys). Human-triggered, agent-executed, resumable.
---

# Daily Sci-Pop Digest

You produce one science-pop article per arXiv paper for the day and publish the site.
Design ref: `docs/superpowers/specs/2026-05-19-daily-digest-deploy-design.md`.
Run everything from the repo root. The user has ample token quota — quality over speed.

## Hard rules

- **No filtering, no triage.** Every paper from the crawl (all categories the
  crawler returns, both `announce_type` `new` AND `cross`) gets a **full**
  article. There is no "short note" tier.
- **Resumable.** Before writing an article, if `data/articles/<id>.md` already
  exists, SKIP that paper. Re-running continues where you stopped.
- **Figure captions must match the image you actually saw.** Never invent a
  caption. If a paper has no usable raster/diagram figure, omit the image and
  say so in the text — do not fabricate.
- Do not touch `daily_arxiv/`. Do not commit `pdfs/`, `data/*.jsonl`,
  `data/rss/` (gitignored).

## Procedure

### 1. Crawl + dedup
```bash
OUT=$(uv run python -m daily_arxiv_rss.crawl)      # prints data/<feed-date>.jsonl
DATE=$(basename "$OUT" .jsonl)                      # e.g. 2026-05-19
uv run python -m daily_arxiv_rss.dedup --data "$OUT"; echo "dedup exit: $?"
```
If dedup exit code is `1` (no new content) → tell the user, STOP.
Exit `2` → report the error, STOP. Exit `0` → continue.

### 2. Download PDFs (gentle, gitignored)
```bash
uv run python -m daily_arxiv_rss.pdf --data "$OUT" --out-dir pdfs
```

### 3. Per paper (iterate every record in `$OUT`)

`id` is the versioned id (e.g. `2605.15202v1`); `arxiv_id` = id without `vN`.
**If `data/articles/<id>.md` exists, skip.**

a. Extract text:
```bash
uv run --with pypdf python - <<'PY'
from pypdf import PdfReader
import sys
r=PdfReader(f"pdfs/{sys.argv[1]}.pdf")
open(f"/tmp/{sys.argv[1]}.txt","w",encoding="utf-8").write(
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
- Write `data/articles/<DATE>.json`:
  `{"date":"<DATE>","_order":"newest first (by arXiv id desc)","articles":[ ... ]}`
  sorted by `arxiv_id` **descending**. Each entry exactly:
  `id, arxiv_id, headline, hook, category_label, importance, authors,
  affiliations, url, pdf, date, md` where `md` = `data/articles/<id>.md`.
  (`importance` may be `"高"`/`"中"`; it is not used for filtering, only display.)
- Ensure `<DATE>` is in `data/articles/index.json` `"dates"` (add if missing).

### 5. Publish
```bash
git add data/articles/index.json data/articles/${DATE}.json \
        data/articles/*.md assets/articles/*.webp
git commit -m "digest: ${DATE} (N articles)"
git push origin main
```
GitHub Pages redeploys automatically. Tell the user the live URL
`https://<owner>.github.io/<repo>/#${DATE}` and the count.

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
- A day is large; if you hit the quota, just re-run `/daily-digest` later —
  step 3's skip-if-exists makes it resume.
- Existing examples to match in voice/length: `data/articles/2605.15217v1.md`,
  `2605.15205v1.md`, `2605.15219v1.md`.
