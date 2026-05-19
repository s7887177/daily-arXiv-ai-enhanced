# 科普文章化 — 預覽版交接筆記 (2026-05-19)

你出門時交辦的:把輸出改成「文章 / 新聞小卡」、參考 `001-news/run-04` 風格、先生幾篇給你看。以下是現況與怎麼看。

## 怎麼看（最重要）

本機伺服器我已經幫你開在背景（port 8000）。瀏覽器打開:

```
http://localhost:8000/news.html
```

- **列表頁** = 新聞小卡（重要度色標籤、分類、吸睛標題、一句話 hook、來源）
- **點任一張卡** = 全文科普文章（marked 渲染 Markdown，含可信度表格、「怎麼看這件事」段落）
- `Esc` 或「← 回列表」返回

若伺服器掛了（重開機等），在 repo 根目錄重跑:

```bash
cd /home/eason/projects/externals/daily-arXiv-ai-enhanced
python3 -m http.server 8000
```

> 必須用 http 伺服器開，不能用 `file://` 直接點開（瀏覽器會擋 fetch）。

## 我做了什麼

1. 用我們新做的 `daily_arxiv_rss.pdf` **真的下載了 3 篇 PDF**（順便端到端驗證了那支工具:ok 3/3）。
2. **讀 PDF 全文**（poppler 沒裝,改用 pypdf 抽文字）後,**手寫 3 篇繁中科普文章**,風格對齊你 `001-news/run-04`:吸睛標題 → 一句話說重點 → 白話分段 → 結果 → 做不到的地方 → 可信度自查表 → 怎麼看這件事。
   - `2605.15217` 英格蘭銀行:AI 房貸核貸「表面公平、內部偏見」（重要度高,公共性最強）
   - `2605.15205` 微軟亞研院:讓 AI「更懂人心」實測常常感覺不到
   - `2605.15219` USC/MIT:AI 自我進化的數學極限
3. 設計了**文章/小卡資料結構**,產出 `data/articles/2026-05-19.json`。
4. 寫了**獨立檢視器** `news.html`（單檔,自帶 CSS,marked 走 CDN;**完全不碰原本 1800 行的 `app.js`**,降低風險）。
5. 驗證:伺服器 200、JSON 合法、卡片欄位齊全。

## 文章資料結構（提案,待你過目）

`data/articles/<date>.json`:`{ "date", "articles": [ ... ] }`,每篇:

| 欄位 | 用途 |
|---|---|
| `id` / `arxiv_id` | 識別（id 帶版本,沿用我們爬蟲決定） |
| `headline` | 小卡標題 + 文章 H1（**重寫過的吸睛中文**,非原始論文名） |
| `hook` | 小卡上的「一句話說重點」,負責吸引點擊 |
| `category_label` / `importance` | 小卡標籤（重要度:高/中/非AI） |
| `original_title` / `authors` / `affiliations` | 文章開頭的論文資訊框 |
| `url` / `pdf` | 連回 arXiv |
| `body_md` | **整篇科普文章（Markdown）** — 真正的內容 |

這是「文章導向」結構,**刻意不沿用上游那套 `tldr/motivation/method/result/conclusion` 五欄**,因為你的目標就是丟掉那個研究格式。

## 還沒做 / 等你回來討論（你交辦的下一步）

- **Skill 怎麼做**:現在這 3 篇是我「手動」當 Claude Code 跑（讀 PDF→寫文章→寫 JSON）。要變成可重複的 skill,需定義:輸入(哪天的 jsonl + 已下載 PDF)、prompt/風格規格、輸出(這個 JSON schema)、品質檢查。`scripts/build_articles_20260519.py` 是這次的一次性產生器,可當 schema 範本。
- **自動化 vs 訂閱**:API 版(舊 `enhance.py`)花錢;CC 訂閱版每 5 小時刷新額度。兩條路要產出**同一個 article JSON 契約**,跟我們做爬蟲時「契約不變、實作可換」一樣。
- **跟現有管線/前端整併**:目前 `news.html` 是平行的乾淨預覽,沒接上 `convert.py`/`app.js`/`data` 分支/部署。整併與部署策略待議(可能新前端直接取代舊 app.js,或共存)。
- **資料來源**:文章目前讀 `data/articles/2026-05-19.json`(本機);真正流程要決定它進不進 `data` 分支、前端怎麼抓。

## Repo 衛生

- 之前為了舊 UI 預覽改的 `js/data-config.js` **已還原**(`news.html` 不依賴它)。
- `pdfs/` 已在 `.gitignore`,不會進 git。
- `data/articles/*.json` 是預覽產物,可由 `scripts/build_articles_20260519.py` 重生,**未加入 git**。
- 已 commit 的只有:`news.html`、`scripts/build_articles_20260519.py`(內含文章原文)、本筆記。分支仍為 `crawl-rss-virtualization`,未 push、未合併。
