# News Scrapper — Data Flow & Logic

## Startup Flow

```
main.py starts
    │
    ├── Load .env configuration
    ├── Load sites.yaml
    ├── Initialize logger (console + file handlers)
    ├── Connect Redis (optional, graceful fallback)
    ├── Initialize ProxyManager (if enabled)
    ├── Initialize JsonStorage
    │
    ├── Discover scrapers:
    │   for each source in sites.yaml:
    │       if enabled:
    │           import sites_scrapers/<name>.py
    │           find BaseScraper subclass with matching name
    │           instantiate with config, proxy, redis
    │
    ├── Start ScraperWorker threads (one per scraper)
    ├── Start Dashboard HTTP server thread
    │
    └── Main thread: periodic status reporting + signal handling
```

## Scraper Worker Loop

Each scraper runs independently in its own thread:

```
ScraperWorker.run()
    │
    ├── scraper.setup()       # one-time init
    │
    └── while not stopped:
        │
        ├── [If quiet hours] → log once → sleep 60s → loop
        │
        ├── [If blocked] → exponential delay (escalates per block) → retry
        │   block_count tracks how many consecutive blocks
        │   delay = random(base_min × factor^n, base_max × factor^n), capped
        │
        ├── scraper.fetch_news()
        │   │
        │   ├── HTTP request to source (API/RSS/HTML)
        │   ├── Parse response
        │   ├── For each article:
        │   │   ├── Check dedup (local set + Redis)
        │   │   ├── Skip if seen
        │   │   ├── Parse date → IST
        │   │   ├── Build standard item dict
        │   │   └── Mark as seen
        │   └── Return list of new items
        │
        ├── storage.save_news(source, items)
        │   │
        │   ├── Group items by date
        │   ├── For each date group:
        │   │   ├── Read existing <date>.json
        │   │   ├── Deduplicate by URL
        │   │   ├── Merge & sort descending
        │   │   └── Atomic write
        │   ├── Mirror the same batch into DATA/DAYWISE/YYYY/MM_MonthName/<date>.json
        │   └── Return count saved
        │
        ├── Buffer items for backup.json
        ├── Periodically flush buffer → backup.json
        │
        ├── Update stats (Redis)
        ├── Log results
        │
        ├── [If error] → increment error count → check blocked threshold
        │
        └── sleep(random(poll_min, poll_max))
```

## Source-Specific Strategies

### Groww (`groww.py`)
- **Method**: JSON API (`/v2/api/feed/public`)
- **Data**: 200 items per page with post IDs
- **Dedup**: `postId` field
- **Date format**: `2026-03-08T10:57:03` (UTC) → IST
- **Poll**: 5-8 seconds

### LiveMint (`livemint.py`)
- **Method**: Dual-source
  - **Fast**: JSON API (`/api/cms/story/latest`) every poll cycle
  - **Slow**: 9 RSS feeds rotated, one per cycle, full sweep ~45s
- **Dedup**: Article URL
- **Date format**: ISO 8601 (API), RFC 2822 (RSS)
- **Poll**: 3-5 seconds

### ScanX (`scanx.py`)
- **Method**: HTML scrape → Angular `<script id="ng-state">` extraction
- **Optimization**: ETag-based conditional requests (304 = no parse needed)
- **Dedup**: Article `id` field
- **Date format**: ISO 8601 with Z suffix
- **Poll**: 8-12 seconds

### TradingView (`tradingview.py`)
- **Method**: Two JSON API endpoints (`streaming=true`, `client=screener`)
  - India-specific: `market_country=IN` + `lang=en_IN`
  - General: `lang=en_IN` (broader coverage)
- **Dedup**: News `id` field
- **Date format**: Unix timestamp
- **Poll**: 2-4 seconds

### Zerodha (`zerodha.py`)
- **Method**: HTML scrape with BeautifulSoup
- **Data**: Main articles + similar/related articles
- **Dedup**: Article URL (href)
- **Date format**: `08:38 AM, 07 Mar 2026` from span title
- **Poll**: 3-5 seconds

### StockEdge (`stockedge.py`)
- **Method**: JSON API (Daily Dashboard)
- **Dedup**: Numeric `ID` field
- **Date format**: `2026-03-09T00:00:00` + `03:45 pm`
- **Poll**: 5-10 seconds

### MoneyControl (`moneycontrol.py`)
- **Method**: HTML scrape with BeautifulSoup
- **Dedup**: Article ID from URL
- **Date format**: Scrape time (not available in listing)
- **Poll**: 5-10 seconds

### Angel One (`angelone.py`)
- **Method**: HTML scrape (Next.js SSR) with BeautifulSoup
- **Dedup**: URL slug
- **Date format**: `9 March 2026` → IST
- **Poll**: 5-10 seconds

## Deduplication Strategy

Three-layer deduplication:

1. **Scraper level** (in `fetch_news`):
   - Local in-memory set of seen IDs/URLs
   - Redis set check (if available): `news_scrapper:seen:<source>`
   - After fetch: bulk mark as seen

2. **Storage level** (in `save_news`):
   - When merging into daily JSON: URL-based dedup
   - When appending to backup.json: URL-based dedup

3. **Cross-restart persistence**:
   - Redis holds seen sets (survive restarts)
   - JSON files themselves serve as ground truth

## Blocked Site Detection

```
Each worker tracks:
    - consecutive_errors: incremented on fetch failure
    - last_success_time: timestamp of last successful fetch
    - block_count: how many consecutive blocks (for escalation)

Blocked condition (either triggers):
    1. consecutive_errors >= MAX_CONSECUTIVE_ERRORS (default: 20)
    2. time_since_last_success >= BLOCKED_THRESHOLD_MINUTES (default: 120)

On block:
    → block_count++
    → Log to blocked.log (with escalation level)
    → Set Redis health status = "blocked"
    → Calculate delay: random(base_min × factor^(n-1), base_max × factor^(n-1))
      capped at BLOCKED_MAX_DELAY_MIN
    → Sleep for calculated delay
    → Reset error counters and retry
    → If still failing, re-enter blocked state (delay escalates)
    → On success: block_count resets to 0
```

## Dashboard API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stats` | GET | Overall stats + per-source stats + worker health |
| `/api/news?source=X&date=Y&limit=N` | GET | News articles with filters |
| `/api/news/<source>?date=Y` | GET | News for specific source |
| `/api/sources` | GET | List of configured sources |
| `/api/dates?source=X` | GET | Available dates |
| `/*` | GET | Static dashboard files |

## Configuration Reference

### `.env` Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `DATA_DIR` | `DATA` | News data directory |
| `DASHBOARD_PORT` | `8080` | Dashboard HTTP port |
| `REDIS_ENABLED` | `true` | Enable Redis integration |
| `REDIS_URL` | `redis://...` | Redis connection string |
| `PROXY_ENABLED` | `false` | Enable proxy rotation |
| `DEFAULT_TIMEOUT` | `20` | HTTP timeout in seconds |
| `BLOCKED_THRESHOLD_MINUTES` | `120` | Minutes before marking blocked |
| `BLOCKED_RETRY_MINUTES` | `30` | Minutes between block retries |
| `BACKUP_WRITE_INTERVAL` | `60` | Seconds between backup.json writes |

### `sites.yaml` Per-Source Settings

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | bool | Enable/disable this source |
| `display_name` | string | Human-readable name |
| `poll_interval` | [min, max] | Seconds between polls |
| `use_proxy` | bool | Route through proxy manager |
| `description` | string | Source description |
