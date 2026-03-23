# News Scrapper — Resilience & Monitoring

How the system handles failures, blocks, rate limits, and runs 24/7 reliably.

---

## Health States

Each scraper worker has one of three states:

| State | Meaning | Dashboard Color | Action |
|-------|---------|----------------|--------|
| **healthy** | Fetching normally, no errors | 🟢 Green | Normal polling |
| **degraded** | Some errors but still fetching | 🟡 Yellow | Increased backoff |
| **blocked** | Source unresponsive for 2+ hours | 🔴 Red | Auto-retry every 30 min |

---

## Error Handling Flow

```
Fetch attempt
    │
    ├── Success → reset error counter, reset block_count, update last_success_time
    │
    └── Failure
        │
        ├── consecutive_errors++
        ├── Log error to errors.log
        │
        ├── if consecutive_errors >= MAX_CONSECUTIVE_ERRORS
        │   └── BLOCKED → block_count++ → exponential backoff → retry
        │
        ├── if time_since_last_success >= BLOCKED_THRESHOLD_MINUTES
        │   └── BLOCKED → block_count++ → exponential backoff → retry
        │
        └── else → linear backoff sleep → retry next cycle
```

### Exponential Backoff

On errors, sleep duration increases:
```
backoff = min(30, poll_max × (1 + consecutive_errors × 0.3))
```

Example with poll_max=10, errors=5: `min(30, 10 × 2.5) = 25 seconds`

---

## Blocked Source Recovery — Exponential Escalation

When a source is marked as blocked, the retry delay **escalates** with each
consecutive block, giving stubborn sources progressively longer rest periods.

### How It Works

1. **First block**: Wait a random delay between `BLOCKED_DELAY_MIN` and
   `BLOCKED_DELAY_MAX` minutes (default: 5–15 min)
2. **Second block**: Range multiplied by `BLOCKED_ESCALATION_FACTOR` (default: ×2)
   → 10–30 min
3. **Third block**: Multiplied again → 20–60 min
4. **Continues escalating** until the cap `BLOCKED_MAX_DELAY_MIN` (default: 120 min)
5. **On success**: `block_count` resets to 0, delay returns to the initial range

### Configuration (`.env`)

```
BLOCKED_DELAY_MIN=5              # Min initial delay (minutes)
BLOCKED_DELAY_MAX=15             # Max initial delay (minutes)
BLOCKED_ESCALATION_FACTOR=2      # Multiplier per consecutive block
BLOCKED_MAX_DELAY_MIN=120        # Absolute ceiling (minutes)
```

### Escalation Example (defaults)

| Block # | Delay Range | Explanation |
|---------|-------------|-------------|
| 1st | 5 – 15 min | Base range (random) |
| 2nd | 10 – 30 min | ×2 escalation |
| 3rd | 20 – 60 min | ×4 |
| 4th | 40 – 120 min | ×8 (capped at 120) |
| 5th+ | 120 min | At cap |

### What Gets Logged

```
[stockedge] BLOCKED — 0 consecutive errors, 120m since last success (escalation level 3)
[stockedge] Blocked (level 3) — retrying in 47m
[stockedge] Retrying after block...
```

---

## Quiet Hours

Scraping can be paused during a configurable time window (IST, 24-hour format).
This is useful for non-market hours or to reduce load during maintenance windows.

### Configuration (`.env`)

```
QUIET_HOURS_START=23:30
QUIET_HOURS_END=06:00
```

Leave both values **empty** to disable.

### Behavior

- Every worker checks the clock at the start of each loop iteration
- If inside the quiet window: log "Quiet hours — paused" once, then sleep 60s
- When the window ends: log "Quiet hours ended — resuming" and resume normal polling
- Cron mode also respects quiet hours (skips cycles during the window)
- Overnight windows (e.g. 23:30 → 06:00) and same-day windows (e.g. 12:00 → 13:00)
  are both supported

---

## Rate Limit Avoidance

### Strategies Used

| Strategy | How | Configured |
|----------|-----|-----------|
| **Randomized interval** | Each poll waits `random(min, max)` seconds | `sites.yaml → poll_interval` |
| **Jitter** | Never hit the same interval twice in a row | Built-in `random.uniform()` |
| **ETag caching** | For ScanX: skip parsing if no change (304) | Automatic |
| **RSS rotation** | LiveMint: only 1 of 9 feeds per cycle | Built-in |
| **Browser-like headers** | Real Chrome user-agent, proper referers | Per-scraper `setup()` |

### If You Get 429 / Rate Limited

1. **Increase poll interval** in `sites.yaml`:
   ```yaml
   groww:
     poll_interval: [10, 15]  # was [5, 8]
   ```

2. **Enable proxy rotation** in `.env`:
   ```
   PROXY_ENABLED=true
   ```
   And set `use_proxy: true` for the affected source in `sites.yaml`

3. **Reduce request volume**: Some scrapers fetch from multiple endpoints;
   you can modify the scraper to use fewer endpoints

---

## Proxy Failover

When proxies are enabled:

1. **Round-robin rotation** — each request uses the next proxy
2. **Bandwidth tracking** — disables proxies that exceed their limit
3. **Error tracking** — disables proxies with 10+ consecutive errors
4. **Auto-recovery** — if all proxies are exhausted, requests go direct (no proxy)

---

## Long-Running Stability

Features that enable 24/7 operation for months/years:

### Memory Management
- **Seen-ID sets**: Grow with data but IDs are small strings; ~100K IDs ≈ 10 MB
- **Backup buffer**: Flushed periodically, never grows unbounded
- **No memory leaks**: Each fetch cycle is independent, no accumulation

### Disk Management
- **Rotating logs**: `scrapper.log` rotates at 10 MB × 10 files = 100 MB max
- **JSON growth**: Daily files are finite; backup.json grows linearly
- **No temp file accumulation**: Atomic writes clean up on success

### Thread Safety
- **Per-source locks** in JsonStorage prevent write conflicts
- **Thread-safe proxy rotation** with internal locking
- **Daemon threads** ensure clean exit when main thread stops

### Signal Handling
- **SIGINT** (Ctrl+C): Sets stop event, all workers flush buffers and exit
- **SIGTERM**: Same as SIGINT (for process managers, systemd, etc.)
- **Graceful timeout**: Workers get 15 seconds to finish before forced exit

---

## Monitoring

### Console Output
Real-time colored log output showing:
```
2026-03-09 11:40:36 INF [groww] +200 new | Total: 200
2026-03-09 11:40:37 INF [tradingview] +372 new | Total: 372
```

### Periodic Status (every 5 minutes)
```
2026-03-09 11:45:36 INF [main] Status: 5/5 alive, 0 blocked, 1159 total articles
```

### Log Files

| File | Contents | Rotation |
|------|----------|----------|
| `logs/scrapper.log` | Everything | 10 MB × 10 files |
| `logs/errors.log` | Errors only | 10 MB × 5 files |
| `logs/blocked.log` | Blocked events only | 10 MB × 5 files |

### Dashboard
- Real-time health cards per source
- Article counts (total + today)
- Uptime indicator
- Last update timestamp

### Redis (if enabled)
Query health from Redis directly:
```bash
redis-cli hgetall news_scrapper:health:groww
redis-cli scard news_scrapper:seen:groww
redis-cli hgetall news_scrapper:stats:groww
```

---

## Disaster Recovery

### Process Crash
1. Restart `python main.py`
2. Redis retains seen-IDs → no duplicate fetches
3. JSON files retain all data → no data loss
4. Workers pick up where they left off

### Data Corruption
If a JSON file gets corrupted:
1. Delete the corrupted file
2. Data will be re-fetched on next poll (if articles are still available from source)
3. backup.json serves as secondary copy

### Redis Down
1. System auto-detects and falls back to file-only mode
2. Warning logged at startup
3. Performance slightly reduced (in-memory dedup only, no cross-restart persistence)
4. When Redis comes back, restart main.py to reconnect

### Disk Full
1. Atomic writes prevent partial file corruption
2. System logs error and continues trying
3. Free up disk space, then no action needed — system self-recovers
