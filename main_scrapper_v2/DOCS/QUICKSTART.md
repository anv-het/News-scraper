# News Scrapper — Quick Start Guide

## Prerequisites

- **Python** 3.10+
- **Redis** (optional but recommended) — dedup + stats caching
- **pip** packages: see `requirements.txt`

## Installation

```bash
cd main_scrapper
pip install -r requirements.txt
```

## Configuration

### 1. `.env` — Master settings

Open `.env` and configure:

| Setting | What it does | Default |
|---------|-------------|---------|
| `LOG_LEVEL` | Console/file log verbosity | `INFO` |
| `DATA_DIR` | Where news JSON is stored | `DATA` |
| `DASHBOARD_ENABLED` | Turn web dashboard on/off | `true` |
| `DASHBOARD_PORT` | HTTP port for dashboard | `8080` |
| `REDIS_ENABLED` | Use Redis for dedup/stats | `true` |
| `REDIS_URL` | Redis connection string | `redis://192.168.102.233:6379/0` |
| `PROXY_ENABLED` | Route through proxy pool | `false` |
| `BLOCKED_THRESHOLD_MINUTES` | Minutes of silence before marking source blocked | `120` |
| `BLOCKED_DELAY_MIN` | Initial min blocked retry delay (minutes) | `5` |
| `BLOCKED_DELAY_MAX` | Initial max blocked retry delay (minutes) | `15` |
| `BLOCKED_ESCALATION_FACTOR` | Multiply delay on each consecutive block | `2` |
| `BLOCKED_MAX_DELAY_MIN` | Maximum blocked retry delay cap (minutes) | `120` |
| `QUIET_HOURS_START` | Pause scraping at this IST time (24h) | _(empty = disabled)_ |
| `QUIET_HOURS_END` | Resume scraping at this IST time (24h) | _(empty = disabled)_ |
| `BACKUP_WRITE_INTERVAL` | Seconds between backup.json flushes | `60` |

### 2. `sites.yaml` — Sources

Enable/disable each news source, set poll intervals:

```yaml
sources:
  groww:
    enabled: true
    display_name: "Groww"
    poll_interval: [5, 8]   # min, max seconds between fetches
    use_proxy: false
    description: "Stock market news from Groww API"
```

### 3. `proxies.txt` — Proxy pool (optional)

One proxy per line: `host:port:username:password`

## Running

```bash
cd main_scrapper
python main.py
```

That's it. The system will:
1. Load all enabled scrapers from `sites.yaml`
2. Start each in its own thread
3. Start the dashboard on the configured port
4. Run indefinitely until Ctrl+C

## Dashboard

Open in browser:
- If main.py is running: **http://localhost:8080**
- If using VS Code Live Server: open `dashboard/index.html` (auto-connects to port 8080)

## Stopping

Press **Ctrl+C** in the terminal. All workers flush their backup buffers and shut down cleanly.

## Logs

Check `logs/` directory:
- `scrapper.log` — all activity (rotating, 10MB × 10 files)
- `errors.log` — errors only
- `blocked.log` — blocked source events

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Failed to load news" on dashboard | Make sure `python main.py` is running (port 8080) |
| Redis connection warning | Set `REDIS_ENABLED=false` in `.env` or fix Redis URL |
| A source shows "blocked" | Check `logs/blocked.log` — source may be rate-limited; it auto-retries |
| No data for a source | Check if `enabled: true` in `sites.yaml`; check `logs/errors.log` |
| Dashboard blank after date change | That date may have no news — pick a date with data |
