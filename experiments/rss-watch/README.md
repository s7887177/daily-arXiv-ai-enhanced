# RSS watch — observe arXiv's RSS dynamics

Background poller that records `cs.AI`, `astro-ph.CO`, `econ.EM` every 30 min
so we can answer questions like "when does arXiv roll the channel pubDate?",
"how fast does a pubDate window accumulate items?", "are different categories'
rolls synchronised?". Run it for 1–2 weeks, then read `stats`.

Output (gitignored under `experiments/rss-watch/`):

  snapshots/<cat>/<fetched-at>.xml   immutable raw RSS bytes, one per fetch
  status.json                        last-fetch summary per cat
  daemon.log                         one line per fetch
  daemon.pid                         PID of running daemon

## Run it

```bash
# start in background, survives terminal close
nohup uv run python -m daily_arxiv_rss.rss_watch daemon \
      > experiments/rss-watch/daemon.out 2>&1 &
disown

# check it
uv run python -m daily_arxiv_rss.rss_watch status
tail -f experiments/rss-watch/daemon.log

# anytime: see the analysis so far
uv run python -m daily_arxiv_rss.rss_watch stats

# stop it
uv run python -m daily_arxiv_rss.rss_watch stop
```

## Useful one-offs

```bash
# fire one fetch right now (also works if daemon isn't running)
uv run python -m daily_arxiv_rss.rss_watch fetch

# change cats or interval
uv run python -m daily_arxiv_rss.rss_watch \
  --cats "cs.AI,cs.CV,math.NA" --interval 900 daemon

# raw snapshot count
ls experiments/rss-watch/snapshots/cs.AI | wc -l
```

## What the stats output tells you

For each category:

- **channel pubDate rolls** — when arXiv changed the channel's pubDate (the
  announcement-day label). Each line shows the snapshot at which the new
  label first appeared.
- **windows observed** — for each distinct channel pubDate seen, how many
  snapshots, the min/max/last item count within that window, and the **union**
  of unique ids seen across all snapshots in the window. The gap between
  `items_last` and `union` tells you how much "rolled out" within the window.
- **per-cycle delta** — between consecutive snapshots, how many ids appeared
  and how many disappeared.
- **rolled out** — total ids that were in the feed at some point but not in
  the most recent snapshot.

**Cross-cat roll alignment** clusters rolls happening within ~10 min across
categories — to see whether rolls are synchronised (likely) or independent.

## What we hope to learn

1. **Roll cadence**: once a day? at a fixed UTC hour? same hour every day?
2. **Within-window growth**: how long does it take a pubDate window to
   stabilise after first appearance? Hours? Most of a day?
3. **Cross-cat synchronisation**: can we use one cat as a probe for all?
4. **Optimal poll frequency**: minimum cadence that catches ≥99% of ids
   while still in the rolling window.

The answers determine what `daily_arxiv_rss.crawl`'s "probe" should look like
and how often `/daily-digest` should naturally be triggered.
