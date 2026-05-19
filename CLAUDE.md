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

# 單獨執行各階段(注意各自的工作目錄):
out=$(uv run python -m daily_arxiv_rss.crawl)              # repo 根目錄;省略 --out=data/<feed pubDate>.jsonl;stdout=該路徑
uv run python -m daily_arxiv_rss.dedup --data "$out"       # 我們自己的去重(吃 feed-date 檔名),退出碼 0/1/2 決定後續
# run.sh/run.yml 以 $out 串接(STOPGAP,暫時);舊 daily_arxiv/check_stats.py 不再呼叫(死碼)
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

### 五階段流水線(`.github/workflows/run.yml` 串接,`run.sh` 為本地對應版)
1. **爬取** `daily_arxiv_rss/`(RSS,取代舊 Scrapy):抓 `rss.arxiv.org/rss/<cat>`,原始 feed 存為 SOT `data/rss/{cat}_YYYYMMDD.xml`,transform 成相同 8 欄位契約輸出 `data/{date}.jsonl`。`id` 改為**帶版本**(`2605.15202v1`)。cross-list 主分類靠跨 feed 比對 `announce_type=new` 還原。舊 `daily_arxiv/`(Scrapy)**保留但不再被呼叫**(`check_stats.py` 仍住在裡面,故保留)。設計/計畫見 `docs/superpowers/specs|plans/2026-05-19-*`。另有手動 PDF 工具 `python -m daily_arxiv_rss.pdf`(本地、不進 CI/git)。
2. **去重** `daily_arxiv_rss/dedup.py`(取代 `check_stats.py`):與過去 **7 天** 的 ID 比對並就地改寫該檔。**日期取自 `--data` 檔名(feed pubDate),不用機器時鐘**——這是能全程對齊 RSS 日期的關鍵。**退出碼即控制流**:`0`=有新內容繼續、`1`=無新內容停止、`2`=錯誤(與舊版契約相同)。舊 `check_stats.py` 不再被呼叫(`daily_arxiv/` 仍原封不動,該檔變死碼)。
3. **AI 增強** `ai/enhance.py`:LangChain + `ChatOpenAI.with_structured_output(Structure)`,產生 `Structure`(`ai/structure.py`:tldr/motivation/method/result/conclusion)五欄位。另外解析摘要中的 GitHub 連結補 star/更新日期。對 LLM 解析失敗有多層 fallback(修復 JSON → 部分資料 → 預設佔位值),不會因單篇失敗中斷整批。
4. **轉 Markdown** `to_md/convert.py`:依分類分組,分類順序按 `CATEGORIES` 偏好排序。輸出 `data/{date}.md`。
5. **發布**:注入設定後,程式碼推 `main`、資料推 `data`,均含 3 次重試 + rebase。

### 檔案命名約定(階段間靠檔名串接,改一處要全鏈一致)
`data/{date}.jsonl` → `data/{date}_AI_enhanced_{LANGUAGE}.jsonl` → `data/{date}.md`

### 設定佔位符注入(讓 fork 後免改程式碼)
`js/data-config.js`(repo owner/name)與 `js/auth-config.js`(密碼 SHA-256)含 `PLACEHOLDER_*` 字串,CI 中用 `sed` 替換。**不要手動編輯 `js/data-config.js`**(檔頭即標明 auto-generated)。

### 敏感詞過濾為外部相依且 fail-closed
`enhance.py` 的 `is_sensitive()` 呼叫原作者的 Cloudflare Worker `spam.dw-dengwei.workers.dev`。**服務異常或逾時時預設回傳 True(判定為敏感)→ 該論文被靜默丟棄**。fork 自用若該服務不可用,可能導致大量論文消失,改動爬取/增強流程時需留意此行為。

### 前端(純靜態,無建置步驟)
`index.html`(主閱讀頁,`js/app.js` ~1800 行)、`statistic.html`(趨勢統計)、`settings.html`(關鍵字/作者偏好,存 localStorage)、`login.html`(選用密碼保護)。資料於瀏覽器端從 `data` 分支抓取。`SKILL/SKILL.md` 定義給 AI agent 用的 URL 取數介面,因頁面需執行 JS 才產生 JSON,須用 `SKILL/scripts/fetch.sh`(puppeteer)而非 curl。
