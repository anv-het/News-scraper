# News Scrapper — Architecture

## Overview

A centralized, modular news aggregation system that runs **24/7**, collecting real-time
news from multiple financial sources with ≤10 second delay. Built for long-term
unattended operation with health monitoring, auto-recovery, and a production-ready dashboard.

## Project Structure

```
main_scrapper/
├── main.py                     # Entry point & orchestrator
├── .env                        # All project settings
├── sites.yaml                  # Source enable/disable & per-site config
├── requirements.txt            # Python dependencies
├── proxies.txt                 # Proxy list (host:port:user:pass)
├── logger.py                   # Professional colored logging + file rotation
│
├── sites_scrapers/             # One file per news source
│   ├── base.py                 # Abstract BaseScraper class
│   ├── groww.py                # Groww API scraper
│   ├── livemint.py             # LiveMint API + RSS scraper
│   ├── scanx.py                # ScanX Angular SSR scraper
│   ├── tradingview.py          # TradingView dual-API scraper
│   ├── zerodha.py              # Zerodha Pulse HTML scraper
│   ├── stockedge.py            # StockEdge Daily Dashboard API scraper
│   ├── moneycontrol.py         # MoneyControl HTML scraper
│   └── angelone.py             # Angel One HTML scraper
│
├── utils/                      # Shared utilities
│   ├── time_utils.py           # IST conversion, time_ago, date parsing
│   ├── proxy.py                # Proxy rotation & bandwidth tracking
│   └── http_client.py          # Session factory with proxy support
│
├── storage/                    # Data persistence layer
│   ├── json_storage.py         # JSON file storage with atomic writes
│   └── redis_cache.py          # Redis for dedup & stats (optional)
│
├── dashboard/                  # Production web dashboard
│   ├── index.html              # Main page
│   ├── style.css               # Dark/light theme professional styling
│   └── app.js                  # Client-side logic with Fuse.js search
│
├── DATA/                       # News data (auto-created)
│   ├── groww/
│   │   ├── 2026-03-09.json     # Daily file (descending order)
│   │   └── backup.json         # All-time archive
│   ├── livemint/
│   ├── scanx/
│   ├── tradingview/
│   ├── zerodha/
│   ├── stockedge/
│   ├── moneycontrol/
│   └── angelone/
│
├── logs/                       # Log files (auto-created)
│   ├── scrapper.log            # Main rotating log
│   ├── errors.log              # Errors only
│   └── blocked.log             # Blocked/failed sources
│
└── DOCS/                       # Documentation
    ├── ARCHITECTURE.md          # This file
    └── FLOW.md                  # Data flow & logic documentation
```

## Component Architecture

### 1. Orchestrator (`main.py`)

The main process is responsible for:
- Loading configuration from `.env` and `sites.yaml`
- Dynamically discovering and instantiating scraper classes
- Running each scraper in its own **daemon thread** (`ScraperWorker`)
- Starting the dashboard HTTP server in a separate daemon thread
- Handling graceful shutdown via SIGINT/SIGTERM
- Periodic health status reporting (every 5 minutes)

### 2. Scrapers (`sites_scrapers/`)

Every scraper extends `BaseScraper` (abstract base class) and implements:

| Method | Purpose |
|--------|---------|
| `name` | Class attribute matching the key in `sites.yaml` |
| `setup()` | One-time initialization (headers, state) |
| `fetch_news()` | Return list of NEW news items in standard format |

The base class provides:
- Session management with configurable User-Agent
- Deduplication helpers (`_is_seen`, `_mark_seen`) backed by Redis + local set
- Standard item builder (`_build_item`) ensuring consistent JSON output
- HTML cleaning, safe HTTP requests

### 3. Storage (`storage/`)

**JsonStorage** (thread-safe):
- Atomic writes via temp file + rename (no corruption on crash)
- Per-source locking to prevent race conditions
- Daily files: `DATA/<source>/<YYYY-MM-DD>.json`
- Backup files: `DATA/<source>/backup.json` (all-time)
- URL-based deduplication within each file

**RedisCache** (optional):
- Seen-ID tracking per source (instant O(1) lookups)
- Stats counters and health status per source
- Proxy bandwidth tracking
- Graceful fallback if Redis is unavailable

### 4. Proxy Manager (`utils/proxy.py`)

- Loads proxies from `proxies.txt` (format: `host:port:user:pass`)
- Thread-safe round-robin or random rotation
- Bandwidth tracking per proxy (with Redis persistence)
- Auto-disables proxies that exhaust bandwidth or accumulate errors

### 5. Logger (`logger.py`)

- **Console**: Colored output with IST timestamps and source tags
- **scrapper.log**: Rotating main log (10MB × 10 files)
- **errors.log**: Errors only
- **blocked.log**: Blocked-site events only (filtered)

### 6. Dashboard (`dashboard/`)

- Built-in HTTP server (no extra dependency)
- REST API: `/api/stats`, `/api/news`, `/api/sources`, `/api/dates`
- Fuse.js for semantic/fuzzy search
- Real-time IST clock
- Source health monitoring cards
- Dark/light theme toggle
- Date picker, source filter tabs, sort controls

## Adding a New Source

1. Create `sites_scrapers/<name>.py`:
   ```python
   from .base import BaseScraper
   
   class MyScraper(BaseScraper):
       name = "<name>"  # must match sites.yaml key
       
       def setup(self):
           # configure session headers etc.
           pass
       
       def fetch_news(self) -> list[dict]:
           # fetch and return new items
           return [self._build_item(dt, caption, summary, url)]
   ```

2. Add to `sites.yaml`:
   ```yaml
   sources:
     <name>:
       enabled: true
       display_name: "Display Name"
       poll_interval: [5, 10]
       use_proxy: false
       description: "Description"
   ```

3. Restart `main.py`. No other changes needed.

## Data Format

Every news item follows this exact structure:

```json
{
    "news_date": "2026-03-09",
    "news_time": "10:30 AM IST",
    "scraped_at": "2026-03-09 10:30:15 IST",
    "news_caption": "Headline text",
    "news_summary": "Summary or description",
    "news_url": "https://example.com/article",
    "time_ago": "5 min ago"
}
```

## Resilience

| Feature | Implementation |
|---------|---------------|
| Crash-safe writes | Atomic file writes (temp + rename) |
| Deduplication | URL-based (JSON) + ID-based (Redis) |
| Blocked detection | 2hr no-data threshold → blocked.log |
| Auto-recovery | Exponential backoff: delays escalate per block, reset on success |
| Rate limiting | Randomized poll intervals with jitter |
| Error backoff | Exponential backoff on consecutive errors |
| Quiet hours | Configurable IST window where all workers pause |
| Long-term run | Daemon threads, rotating logs, bounded memory |
