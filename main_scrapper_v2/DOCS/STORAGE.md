# News Scrapper — Storage & Data Documentation

## Data Directory Layout

```
DATA/
├── groww/
│   ├── 2026-03-07.json      ← Source daily file
│   ├── 2026-03-08.json
│   ├── 2026-03-09.json
├── livemint/
├── scanx/
├── tradingview/
├── zerodha/
└── DAYWISE/
  └── 2026/
    └── 03_March/
      └── 2026-03-09.json ← Aggregated daywise file across sources
└── backup.json            ← Shared all-time archive across all sources
```

Source archives remain the ingestion layer. Daywise files are a mirrored aggregate that is updated whenever new articles are saved and can also be backfilled from existing source JSON files.

## JSON Schema

### Source Daily File (`DATA/<source>/<date>.json`)

Array of news items sorted **descending** by date+time (newest first):

```json
[
  {
    "news_date": "2026-03-09",
    "news_time": "05:07 PM IST",
    "scraped_at": "2026-03-09 11:40:36 IST",
    "news_caption": "Cupid Jumps 15% on Ex-Bonus Trade Amid Market Turmoil",
    "news_summary": "Cupid's share price surged 15% as the stock traded ex-bonus...",
    "news_url": "https://groww.in/stocks/cupid-ltd",
    "time_ago": "5 min ago"
  },
  {
    "news_date": "2026-03-09",
    "news_time": "04:55 PM IST",
    "scraped_at": "2026-03-09 11:40:36 IST",
    "news_caption": "Another headline...",
    "news_summary": "...",
    "news_url": "...",
    "time_ago": "17 min ago"
  }
]
```

### Field Reference

| Field | Type | Format | Description |
|-------|------|--------|-------------|
| `news_date` | string | `YYYY-MM-DD` | Publication date in IST |
| `news_time` | string | `HH:MM AM/PM IST` | Publication time in IST |
| `scraped_at` | string | `YYYY-MM-DD HH:MM:SS IST` | When we fetched it |
| `news_caption` | string | free text | Headline / title |
| `news_summary` | string | free text | Article summary (may be empty) |
| `news_url` | string | URL | Link to original article |
| `time_ago` | string | human readable | Relative time (e.g., "5 min ago") |

### Daywise File (`DATA/DAYWISE/YYYY/MM_MonthName/<date>.json`)

Same article schema as source daily files, but aggregated across all sources for a given date.

### Dashboard API adds:

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | Source name (e.g., "groww") — persisted in source and daywise files |

### Shared `backup.json`

Same schema as daily files but contains **all articles ever collected** across all sources.
Sorted descending by date+time. Written periodically (every `BACKUP_WRITE_INTERVAL` seconds).

---

## Deduplication

### Three Layers

1. **Scraper level** (per fetch cycle):
   - In-memory `set()` of seen IDs/URLs (per scraper instance)
   - Redis `SISMEMBER` check if Redis is available
   - Fastest — prevents duplicate API processing

2. **Storage level** (per file write):
   - When merging new items into daily JSON: URL-based dedup
  - When appending to backup.json: source + URL-based dedup
   - Ensures file-level consistency even after restarts

3. **Cross-restart persistence**:
   - Redis sets survive process restarts (seen IDs stay)
   - JSON files serve as ground truth — re-reads on conflict

### ID Types by Source

| Source | Dedup Key | Type | Example |
|--------|-----------|------|---------|
| Groww | `postId` | string | `"abc123"` |
| LiveMint | news URL | string | `"https://www.livemint.com/..."` |
| ScanX | article `id` | int→string | `"45678"` |
| TradingView | news `id` | string | `"DJN_DN20260309..."` |
| Zerodha | article URL | string | `"https://economictimes.com/..."` |

---

## Atomic Writes

All JSON files are written atomically to prevent corruption:

```
1. Write to temp file in same directory
2. os.replace(temp, target)  ← atomic on same filesystem
```

This means:
- **No partial writes** — file is always complete
- **Crash-safe** — if process dies during write, temp file is orphaned (not the real file)
- **Thread-safe** — per-source locks prevent concurrent writes to same file

---

## Storage Class API

### `JsonStorage`

```python
storage = JsonStorage(data_dir="DATA")

# Save new articles (returns count actually saved after dedup)
saved = storage.save_news("groww", [item1, item2, ...])

# Append to backup
storage.append_backup("groww", [item1, item2, ...])

# Read news (for dashboard)
news = storage.get_news(source="groww", date="2026-03-09", limit=500)
all_news = storage.get_news(source=None, date="2026-03-09", limit=1000)

# Stats
stats = storage.get_stats()
# → {"sources": {"groww": {"total_articles": 201, "today_articles": 56, ...}}, "total_articles": 1159}
```

---

## Redis Data Structures

When Redis is enabled, these keys are maintained:

| Key Pattern | Type | Contents |
|------------|------|----------|
| `news_scrapper:seen:groww` | SET | All seen article IDs for Groww |
| `news_scrapper:seen:livemint` | SET | All seen article URLs for LiveMint |
| `news_scrapper:stats:groww` | HASH | `{total_fetched: "201", last_fetch_time: "1741502436.5"}` |
| `news_scrapper:health:groww` | HASH | `{status: "healthy", detail: "", updated_at: "..."}` |
| `news_scrapper:proxy:bw:1.2.3.4:8080` | STRING | Bytes used by that proxy |

### Redis Failure Handling

If Redis is unavailable:
- **Startup**: Logs a warning, falls back to file-only dedup
- **Runtime**: All Redis operations silently fail (try/except)
- **No data loss**: JSON files are the source of truth, Redis is an optimization

---

## File Sizes (Typical)

| File Type | Typical Size | Growth |
|-----------|-------------|--------|
| Daily JSON (busy day) | 200 KB – 2 MB | ~500 articles |
| Daily JSON (quiet day) | 10 KB – 50 KB | ~50 articles |
| backup.json (1 month) | 5 MB – 30 MB | Grows continuously |
| backup.json (1 year) | 60 MB – 300 MB | Consider archiving |

### Long-Term Management

For very long runs (months/years), backup.json files will grow large.
Consider periodic archiving:

```bash
# Archive old backups
cp DATA/backup.json DATA/backup_2026_Q1.json
# Then clear and let it rebuild from current seen-IDs
```
