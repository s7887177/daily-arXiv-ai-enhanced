# AI Paper Taiwan
這是一個專門生產給台灣人看 AI Paper 介紹文章的科普網站，每天從 Arxiv 上 cs.AI 類 (包含非 primary) 抓下來所有 articles 的 PDF, 並用 AI 寫成科普文章。

## Prerequsite
- 任何可以使用skills的code agent (我是用 Claude Code, Model 選 Claude Sonnet 4.6, effort high 性價比最高. 但聽說 Gemini Flash 生文章效果更好)

## Get Started
進到code agent cli 程式，使用 `/daily-digest` skill。視情況跑 `/init` 增強後續效果。  
`uv python install` 安裝依賴。
`.venv/bin/activate` 進虛擬環境。
`python -m http.server` 跑本地網頁。

## Deployment
Github Page 要打開，設 `main` branch，之後每次push會自動部署。

## Introduction
這個專案原本是從另一個 repo fork 來的，它原本有設一些 github actions 可以每天抓文章，但我們不用那些功能了，因為API KEY很貴，訂閱制讓code agent跑比較划算。  
`/daily-digest` skill 會跑以下流程：
1. 從 arxiv 上抓 rss
2. 整理成我們的格式存起來
3. 判斷哪些PDF還沒抓下來的抓下來
4. 判斷那些PDF還沒有被寫成科普文章的寫成科普文章
5. 更新發布列表

## 手動跑每一步
```sh
python -m daily_arxiv_rss.crawl # 從 arxiv 上抓 rss
```
