# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

零基礎設施的 arXiv 論文每日爬取 + LLM 摘要工具,完全依賴 GitHub Actions(每天 UTC 01:30 觸發)與 GitHub Pages 運行,不需要伺服器。流程:爬取 arXiv 新論文 → 去重 → LLM 生成結構化摘要 → 轉 Markdown → 發布到靜態網頁。

> README 頂部有法律警示:對學術資料有審查要求的法域需謹慎運行,二次分發需自行履行合規審查義務。

## 開發指令

需 Python ≥ 3.12,使用 [uv](https://astral.sh/uv) 管理相依套件。

```bash
uv sync                          # 安裝相依套件,建立 .venv
source .venv/bin/activate

# 完整本地流程(會偵測環境變數,缺 OPENAI_API_KEY 時可跑部分流程)
bash run.sh                      # 必須在 repo 根目錄執行

# RSS 模組(新模型;見 .claude/skills/daily-digest/POLICY.md)
uv run python -m daily_arxiv_rss.crawl       # 探子 → 早退 / 全抓 → per-pubDate jsonl;exit 0=有新,1=no-op,2=err
uv run python -m daily_arxiv_rss.status      # JSON snapshot + decision(any-time entry)
uv run python -m daily_arxiv_rss.pdf         # 自己從 data/*.jsonl + pdfs/ 推導工作;只存冷卻 in .state/rss/pdf-failures.json
uv run python -m daily_arxiv_rss.wave --wave 100 --per 10   # 切下一波 subagent 工作清單
uv run python -m daily_arxiv_rss.manifest    # 用每篇自己的 pub_date 重建 per-pubDate manifest + index.json

# 舊上游 AI 管線(已不再走;留檔)
cd ai && python enhance.py --data ../data/<date>.jsonl --max_workers 4
cd to_md && python convert.py --data ../data/<date>_AI_enhanced_<LANGUAGE>.jsonl
python update_readme.py          # 由 data/*.md 重新產生 README.md
```

**測試**:`daily_arxiv_rss/` 有 pytest 套件(`uv run pytest`);其餘舊管線(`ai/`、`to_md/`、`daily_arxiv/`)**無測試、無 linter**,驗證改動需實際跑流水線。

## 設定方式:全部由環境變數驅動

所有行為由環境變數控制(CI 中來自 GitHub Secrets/Variables):

- `OPENAI_API_KEY` / `OPENAI_BASE_URL` — LLM 端點(預設相容 OpenAI 介面,實務上用 DeepSeek)
- `MODEL_NAME` — 預設 `deepseek-chat`
- `CATEGORIES` — 逗號分隔的 arXiv 分類,如 `cs.CV, cs.CL`
- `LANGUAGE` — 摘要語言,如 `Chinese` / `English`
- `TOKEN_GITHUB` — 選用,用於查 GitHub repo 的 star/更新時間
- `ACCESS_PASSWORD` — 選用,設定後啟用網頁密碼保護

`daily_arxiv/config.yaml` 看似設定檔,但流水線程式碼讀的是環境變數,**不讀 config.yaml**(視為遺留檔案,改它無效)。

## 架構重點(跨檔案才看得懂的部分)

### 雙分支策略
程式碼在 `main` 分支,**產生的資料檔在獨立的 `data` 分支**(workflow 用 orphan 分支 + 暫存目錄搬運實現)。前端透過 `raw.githubusercontent.com/<owner>/<repo>/data/...` 直接抓資料,使程式碼倉庫不被大量資料檔污染。本地通常只有 `main`;`data` 分支僅存在於遠端。

### RSS 模組(`daily_arxiv_rss/`)的承諾
跨檔案才能看懂的是「**每篇論文歸屬日 = 它自己 RSS item 的 pubDate**」這條核心政策,以及伴隨的狀態管理。詳見 `.claude/skills/daily-digest/POLICY.md`(政策)和 `SKILL.md`(機制)。**那兩份是 source of truth**,以下只是地圖:

- **`crawl.py`**:探子先抓第一個 cat → GUID set hash 跟 `.state/rss/last-fetch.json` 比 → 一樣就 exit 1(no-op,artifacts 完全不動)。有變才全抓所有 cat + cross feeds。SOT 存 `data/rss/<cat>_<ISO-UTC>.xml`,**永不覆蓋**。每筆 record 帶自己的 `pub_date`,寫進 `data/<pub_date>.jsonl`(append-only-by-id)。**不寫入 pdf 模組的 state**。
- **`pdf.py`**:**self-contained,filesystem 為真理**。從 `data/*.jsonl` 推「要抓」、從 `pdfs/<id>.pdf` size>0 推「已抓」。eligible = wanted - have - cooldown。成功**不留 state**;失敗才寫進 `.state/rss/pdf-failures.json` 帶 `retry_after`。pidfile `.state/rss/pdf.pid` 防止兩個 daemon 同時跑。直接打 `arxiv.org/pdf/<id>`,**不走 arxiv 套件**(它打 `/api` 違反 robots.txt 且常 hang)。預設 15s/req 依 robots.txt Crawl-delay。
- **`status.py`**:`python -m daily_arxiv_rss.status` 印 JSON snapshot + `decision`(`all_done|write_articles|start_pdf|wait_for_pdfs`),給 `/daily-digest` skill 當 state-aware entry。
- **`wave.py`**:跨**所有** `data/*.jsonl` 找有 PDF、沒文章的 id,切成 per-subagent worklist 給 `/daily-digest` 並行處理。
- **`manifest.py`**:每篇 article 按**它自己的 pub_date** 分組,寫每個 `data/articles/<pub_date>.json`。同一個 pubDate 的 calendar 條目會跨多天慢慢長大(arXiv 會 24h 內陸續補同一公告窗)。
- **`.state/rss/`**(gitignored):`journal.jsonl` 記事、`last-fetch.json`(crawl)、`pdf-failures.json`(pdf,只記冷卻)、`pdf.pid`(pdf daemon lock)。本機狀態,不進 git。
- **退役**:舊 `dedup.py`、舊「pending/ok queue」概念都已死(append-only-by-id + filesystem-as-truth 取代);舊 `daily_arxiv/check_stats.py` 與舊 Scrapy 管線仍在 `daily_arxiv/` 不被呼叫(死碼)。

### 舊上游 AI 管線(死碼,不再呼叫;留檔僅供考古)
這條 fork 已改成「Claude Code subscription 寫科普文章」的路子(見 `/daily-digest` skill),以下這些步驟**不再執行**,改它們對網站無效:
- `ai/enhance.py`:LangChain + `ChatOpenAI.with_structured_output(Structure)`(tldr/motivation/method/result/conclusion)。`is_sensitive()` 呼叫 `spam.dw-dengwei.workers.dev`,**fail-closed**(服務掛掉會把論文判定為敏感丟棄)。
- `to_md/convert.py`:依分類分組成 `data/{date}.md`。
- 舊雙分支發布:程式碼推 `main`、資料推 `data` 分支。**新流程不用 `data` 分支**,前端從 `main` 直接讀 `data/articles/**`。

### 設定佔位符注入(讓 fork 後免改程式碼)
`js/data-config.js`(repo owner/name)與 `js/auth-config.js`(密碼 SHA-256)含 `PLACEHOLDER_*` 字串,CI 中用 `sed` 替換。**不要手動編輯 `js/data-config.js`**(檔頭即標明 auto-generated)。

### 敏感詞過濾為外部相依且 fail-closed
`enhance.py` 的 `is_sensitive()` 呼叫原作者的 Cloudflare Worker `spam.dw-dengwei.workers.dev`。**服務異常或逾時時預設回傳 True(判定為敏感)→ 該論文被靜默丟棄**。fork 自用若該服務不可用,可能導致大量論文消失,改動爬取/增強流程時需留意此行為。

### 前端(純靜態,無建置步驟)
`index.html`(主閱讀頁,`js/app.js` ~1800 行)、`statistic.html`(趨勢統計)、`settings.html`(關鍵字/作者偏好,存 localStorage)、`login.html`(選用密碼保護)。資料於瀏覽器端從 `data` 分支抓取。`SKILL/SKILL.md` 定義給 AI agent 用的 URL 取數介面,因頁面需執行 JS 才產生 JSON,須用 `SKILL/scripts/fetch.sh`(puppeteer)而非 curl。
