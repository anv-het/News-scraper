# News Scrapper — Configuration Reference

Complete reference for all configuration files and settings.

---

## `.env` — Master Configuration

### General

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROJECT_NAME` | string | `NewsScrapper` | Project name shown in logs |
| `LOG_LEVEL` | string | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `DATA_DIR` | string | `DATA` | Root directory for news data |
| `LOG_DIR` | string | `logs` | Root directory for log files |
| `TIMEZONE` | string | `Asia/Kolkata` | Reference timezone (all times are IST) |

### Dashboard / API Server

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DASHBOARD_ENABLED` | bool | `true` | Start the built-in HTTP dashboard |
| `DASHBOARD_HOST` | string | `0.0.0.0` | Bind address (`0.0.0.0` = all interfaces) |
| `DASHBOARD_PORT` | int | `8080` | HTTP port for dashboard + API |

### Redis

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `REDIS_ENABLED` | bool | `true` | Enable Redis for dedup + stats |
| `REDIS_URL` | string | `redis://192.168.102.233:6379/0` | Redis connection URL |
| `REDIS_PREFIX` | string | `news_scrapper` | Key prefix for all Redis keys |
| `REDIS_SEEN_TTL_DAYS` | int | `90` | TTL for seen-ID entries (days) |

**Redis key structure:**
```
news_scrapper:seen:<source>          → SET of seen article IDs
news_scrapper:stats:<source>         → HASH {total_fetched, last_fetch_time}
news_scrapper:health:<source>        → HASH {status, detail, updated_at}
news_scrapper:proxy:bw:<host>:<port> → STRING (bytes used)
```

### Proxy

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PROXY_ENABLED` | bool | `false` | Route requests through proxy pool |
| `PROXY_FILE` | string | `proxies.txt` | Path to proxy list file |
| `PROXY_BANDWIDTH_LIMIT_MB` | int | `1024` | Bandwidth limit per proxy (MB/month) |
| `PROXY_ROTATION` | string | `round_robin` | Rotation strategy: `round_robin` or `random` |

### Scraper Behavior

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DEFAULT_TIMEOUT` | int | `20` | HTTP request timeout (seconds) |
| `DEFAULT_POLL_MIN` | int | `5` | Default minimum poll interval (seconds) |
| `DEFAULT_POLL_MAX` | int | `10` | Default maximum poll interval (seconds) |
| `MAX_RETRIES` | int | `3` | Max retries per failed request |
| `MAX_CONSECUTIVE_ERRORS` | int | `20` | Errors before marking source as blocked |
| `BLOCKED_THRESHOLD_MINUTES` | int | `120` | Minutes of no data before blocking |
| `BACKUP_WRITE_INTERVAL` | int | `60` | Seconds between backup.json flushes |

### Quiet Hours

Pause all scraping during a specified time window (IST, 24-hour format).  
Leave both empty to disable.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `QUIET_HOURS_START` | string | _(empty)_ | Start of quiet window, e.g. `23:30` |
| `QUIET_HOURS_END` | string | _(empty)_ | End of quiet window, e.g. `06:00` |

Examples:
- **Overnight pause**: `QUIET_HOURS_START=23:30` / `QUIET_HOURS_END=06:00`
- **Midday pause**: `QUIET_HOURS_START=12:00` / `QUIET_HOURS_END=13:00`
- **Disabled**: leave both values empty

During quiet hours every worker thread pauses and logs once. Scraping
resumes automatically when the end time is reached.

### Blocked Site Exponential Backoff

When a source is marked as blocked, the retry delay starts with a random
value between `BLOCKED_DELAY_MIN` and `BLOCKED_DELAY_MAX` minutes, and
escalates by `BLOCKED_ESCALATION_FACTOR` on each consecutive block until
it reaches `BLOCKED_MAX_DELAY_MIN`. The delay resets to the initial range
once the source successfully fetches data again.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `BLOCKED_DELAY_MIN` | int | `5` | Minimum initial blocked retry delay (minutes) |
| `BLOCKED_DELAY_MAX` | int | `15` | Maximum initial blocked retry delay (minutes) |
| `BLOCKED_ESCALATION_FACTOR` | float | `2` | Multiply delay range by this on each consecutive block |
| `BLOCKED_MAX_DELAY_MIN` | int | `120` | Absolute cap for the retry delay (minutes) |

**Example escalation** (with defaults):

| Block # | Delay range | Explanation |
|---------|-------------|-------------|
| 1st | 5 – 15 min | Base range |
| 2nd | 10 – 30 min | ×2 |
| 3rd | 20 – 60 min | ×4 |
| 4th | 40 – 120 min | ×8 (capped at 120) |
| 5th+ | 120 min | At cap |

### User Agent

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `USER_AGENT` | string | Chrome 145 UA | HTTP User-Agent for all requests |

---

## `sites.yaml` — Source Configuration

### Structure

```yaml
sources:
  <source_name>:          # Must match scraper's `name` attribute
    enabled: true/false   # Enable or disable this source
    display_name: "Name"  # Human-readable name for dashboard
    poll_interval: [5, 10] # [min_seconds, max_seconds] between fetches
    use_proxy: false      # Route this source through proxy pool
    description: "..."    # Description shown in dashboard
```

### Current Sources

| Name | Display | Poll (s) | Method | Dedup By |
|------|---------|----------|--------|----------|
| `groww` | Groww | 2-4 | JSON API | postId |
| `livemint` | LiveMint | 2-3 | JSON API + 9 RSS feeds | URL |
| `scanx` | ScanX | 3-5 | HTML (Angular ng-state) + ETag | article ID |
| `tradingview` | TradingView | 2-4 | 2 JSON APIs (India + general) | news ID |
| `zerodha` | Zerodha Pulse | 3-5 | HTML scrape (BeautifulSoup) | URL |
| `stockedge` | StockEdge | 5-10 | JSON API (Daily Dashboard) | ID |
| `moneycontrol` | MoneyControl | 5-10 | HTML scrape (BeautifulSoup) | article ID |
| `angelone` | Angel One | 5-10 | HTML scrape (BeautifulSoup) | URL slug |

### Disabling a Source

Simply set `enabled: false`:

```yaml
sources:
  groww:
    enabled: false    # Groww scraper will not start
```

No code changes or restart needed (well, restart `main.py` to pick up the change).

---

## `proxies.txt` — Proxy Pool

### Format

```
# Comments start with #
host:port:username:password
```

### Supported Types

- **Bright Data** residential proxies
- **Standard HTTP/HTTPS** proxies with auth
- Any proxy supporting `http://user:pass@host:port` format

### Bandwidth Tracking

Each proxy is tracked independently. When a proxy exhausts its bandwidth
(defined by `PROXY_BANDWIDTH_LIMIT_MB`), it is automatically disabled.
If Redis is enabled, bandwidth counters persist across restarts.

---

## Dashboard API Endpoints

| Endpoint | Method | Params | Returns |
|----------|--------|--------|---------|
| `/api/stats` | GET | — | Global stats, per-source stats, worker health, uptime |
| `/api/news` | GET | `?source=X&date=YYYY-MM-DD&limit=N` | News articles array |
| `/api/news/<source>` | GET | `?date=YYYY-MM-DD&limit=N` | News for one source |
| `/api/sources` | GET | — | Array of configured sources |
| `/api/dates` | GET | `?source=X` | Array of dates with data |

### Example Responses

**`GET /api/stats`**
```json
{
  "sources": {
    "groww": {
      "total_articles": 201,
      "today_articles": 56,
      "last_article": "2026-03-09 05:07 PM IST",
      "dates_available": ["2026-03-09", "2026-03-08", ...]
    }
  },
  "total_articles": 1159,
  "uptime_seconds": 3600,
  "workers": {
    "groww": {
      "status": "healthy",
      "total_fetched": 201,
      "consecutive_errors": 0,
      "is_blocked": false,
      "poll_interval": [5, 8]
    }
  }
}
```

**`GET /api/news?date=2026-03-09&limit=5`**
```json
[
  {
    "news_date": "2026-03-09",
    "news_time": "05:07 PM IST",
    "scraped_at": "2026-03-09 11:40:36 IST",
    "news_caption": "Headline here",
    "news_summary": "Summary text",
    "news_url": "https://example.com/article",
    "time_ago": "5 min ago",
    "source": "groww"
  }
]
```
