# News Scrapper — Logging Documentation

## Log Levels

| Level | Use Case | Shown in console | Shown in file |
|-------|----------|-----------------|---------------|
| `DEBUG` | Detailed debugging info | Only if LOG_LEVEL=DEBUG | ✅ |
| `INFO` | Normal operations (+N new articles, started, etc.) | ✅ | ✅ |
| `WARNING` | Non-critical issues (Redis down, retry) | ✅ | ✅ |
| `ERROR` | Failed operations (fetch error, parse error) | ✅ | ✅ + errors.log |
| `CRITICAL` | System-level failures | ✅ | ✅ + errors.log |

Set level in `.env`:
```
LOG_LEVEL=INFO
```

---

## Log Files

| File | Contents | Rotation | Max Disk |
|------|----------|----------|----------|
| `logs/scrapper.log` | All log messages | 10 MB × 10 files | 100 MB |
| `logs/errors.log` | ERROR + CRITICAL only | 10 MB × 5 files | 50 MB |
| `logs/blocked.log` | Blocked-source events only | 10 MB × 5 files | 50 MB |

Total maximum disk usage: **200 MB** (auto-rotated, never grows beyond this).

---

## Console Format (Colored)

```
2026-03-09 11:40:36 INF [groww] +200 new | Total: 200
│                    │   │       └── message
│                    │   └── source tag (magenta)
│                    └── level tag (green=INF, yellow=WRN, red=ERR)
└── IST timestamp (dim white)
```

### Color Coding

| Level | Color |
|-------|-------|
| DBG | Cyan |
| INF | Green |
| WRN | Yellow |
| ERR | Red |
| CRT | Bright Red |
| Source tag | Magenta |
| Timestamp | Dim White |

---

## File Format (Plain)

```
2026-03-09 11:40:36 INFO     [groww] +200 new | Total: 200
2026-03-09 11:40:37 ERROR    [tradingview] Fetch error: Connection timeout
2026-03-09 13:40:36 WARNING  [scanx] BLOCKED — 20 consecutive errors, 120m since last success
```

---

## Using the Logger in Code

### For scraper workers (automatic)
Each `ScraperWorker` has a `SourceLogger` that auto-tags messages with the source name.
The scraper code doesn't need to handle logging — the worker does it.

### For custom code

```python
import logging
from logger import SourceLogger

logger = logging.getLogger("scrapper")
slog = SourceLogger(logger, "my_component")

slog.info("Starting processing")
slog.warning("Slow response from API")
slog.error("Failed to parse response")
slog.blocked("Source is unreachable for 2 hours")  # → goes to blocked.log
```

---

## Log Interpretation Examples

### Healthy Operation
```
INF [main] NewsScrapper starting...
INF [redis] Redis connected: redis://192.168.102.233:6379/0
INF [main] Loaded 5 scrapers: ['groww', 'livemint', 'scanx', 'tradingview', 'zerodha']
INF [groww] Started | poll: 5-8s
INF [groww] +200 new | Total: 200
INF [tradingview] +372 new | Total: 372
INF [main] Status: 5/5 alive, 0 blocked, 1159 total articles
```

### Source Having Issues
```
ERR [scanx] Fetch error: ConnectionError: HTTPSConnectionPool...
ERR [scanx] Fetch error: ConnectionError: HTTPSConnectionPool...
WRN [scanx] BLOCKED — 20 consecutive errors, 125m since last success
INF [scanx] Retrying after block...
INF [scanx] +3 new | Total: 50  ← recovered!
```

### Redis Unavailable
```
WRN [redis] Redis unavailable (Connection refused), falling back to file-based dedup
INF [main] Loaded 5 scrapers...  ← continues without Redis
```
