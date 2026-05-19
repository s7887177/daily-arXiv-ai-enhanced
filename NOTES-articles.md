# 科普文章化 — 預覽版交接筆記 (2026-05-19，已套用你的回饋)

## 怎麼看

伺服器我已在背景開好（port 8000）。瀏覽器打開:

```
http://localhost:8000/news.html
```

掛了就在 repo 根目錄重跑 `python3 -m http.server 8000`（必須 http，不能 file://）。

## 你這輪的回饋，逐項處理狀況

| 你的要求 | 狀態 | 做法 |
|---|---|---|
| 點進去要有大標題 | ✅ | 每篇 `.md` 第一行就是 `# 標題`，marked 渲染成大 H1 |
| 要有圖片＋圖片解釋 | ✅ | 用 PyMuPDF 從 PDF 取出**真實的關鍵圖**（我逐張肉眼確認過內容），每篇嵌一張＋一段白話圖解 |
| 黑底白字、只有一種粗體強調、不要強調色 | ✅ | 全站黑底 (#000) 白字；`strong` 只用 `font-weight:700`（無顏色）；移除所有強調色，純單色 |
| 點開跳到專屬可分享 URL（無後端） | ✅ | 用 hash 路由：`news.html#2605.15217v1`。靜態可分享、`hashchange` 可前後退，免後端 |
| 閱讀時左右固定永遠有上一篇/下一篇 | ✅ | 視窗左右垂直置中固定鈕，永遠可見；首/末篇自動隱藏該側；另支援 ← → 鍵與 Esc |
| 文章直接輸出 md，json 只存路徑 | ✅ | 見下方架構 |

## 資料架構（已照你說的改成 md＋manifest）

```
data/articles/
  2026-05-19.json          # manifest：只存中繼資料 + md 路徑，無內文
  2605.15217v1.md          # 一篇文章 = 一個獨立 markdown（# 標題開頭、含圖、run-04 風格）
  2605.15205v1.md
  2605.15219v1.md
assets/articles/
  2605.15217v1-fig1.png    # 從 PDF 取出的關鍵圖（已肉眼校對 + 圖解與圖相符）
  2605.15205v1-fig1.png
  2605.15219v1-fig1.png
news.html                  # 讀 manifest 出小卡；點開 fetch 該 .md 用 marked 渲染
```

manifest 每篇欄位：`id, arxiv_id, headline, hook, category_label, importance, authors, affiliations, url, pdf, date, md`。**沒有 body**——文章本體在 `.md`，這也讓未來「AI agent 直接寫一個 .md 檔」變成最自然的 skill 介面。

3 篇文章（都讀 PDF 全文後手寫，繁中科普、run-04 結構）：
- `2605.15217` 英格蘭銀行：AI 房貸核貸表面公平、內部偏見逐層放大、可被便宜引爆（重要度高）
- `2605.15205` 微軟亞研院：讓 AI「更懂人心」實測常常感覺不到
- `2605.15219` USC/MIT：AI 自我進化的數學極限與「污染陷阱」

## 還沒做 / 等你回來討論

- **Skill 化**：現在這 3 篇是我手動當 Claude Code 跑（下載 PDF → 讀 → 寫 .md → 補 manifest 一筆）。未來 skill 的介面已經很乾淨：輸入=當天 jsonl + 已下載 PDF；輸出=一個 `.md` 檔 + manifest 追加一筆 + 一張裁好的圖。風格規格（run-04 結構、圖解要對應實際圖）待寫成 skill 文件。
- **自動化 vs 訂閱額度**：API 版 vs Claude Code 訂閱版兩條路，產出同一個 md＋manifest 契約（同「契約不變、實作可換」思路）。
- **與舊管線/部署整併**：`news.html` 目前是平行乾淨預覽，沒接 `convert.py`/舊 `app.js`/`data` 分支/GitHub Pages。新前端取代還是共存、靜態部署怎麼弄，待議。
- **圖片取得的限制**：PyMuPDF 能算穩，但「裁切框」目前是我估的比例 + 肉眼校對；skill 化時要想更穩的取圖法（或讓 agent 自己看圖定位）。

## Repo 衛生

- `js/data-config.js` 舊 hack 已還原（`news.html` 不依賴它）。
- `pdfs/` 仍 gitignore（大、可重抓）。
- 已 commit：`news.html`、`data/articles/*.md`、`data/articles/2026-05-19.json`(manifest)、`assets/articles/*-fig1.png`、本筆記；並刪除上一版的嵌入式產生器。分支仍 `crawl-rss-virtualization`，未 push、未合併。
