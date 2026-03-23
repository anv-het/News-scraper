# News Scrapper — Adding New Sources

This guide explains how to add a new news source to the scrapper in **under 5 minutes**.

## Step 1: Create the Scraper File

Create `sites_scrapers/<source_name>.py`:

```python
"""
<Source Name> News Scraper
Source: <URL>
Method: <API / RSS / HTML scrape>
Dedup: by <id field / URL>
"""

from .base import BaseScraper
from utils.time_utils import parse_iso_datetime  # or whichever parser fits


class MySourceScraper(BaseScraper):
    name = "my_source"  # MUST match the key in sites.yaml

    # Your source URLs
    API_URL = "https://example.com/api/news"

    def setup(self):
        """Called once before polling starts. Set headers, init state."""
        self.session.headers.update({
            "Accept": "application/json",
            "Referer": "https://example.com/",
        })

    def fetch_news(self) -> list[dict]:
        """
        Fetch latest news. Return ONLY new items (not seen before).
        Must return list of dicts built with self._build_item().
        """
        resp = self._safe_get(self.API_URL)
        if not resp:
            return []

        try:
            data = resp.json()
        except ValueError:
            return []

        new_items = []
        new_ids = []

        for article in data.get("articles", []):
            # Unique ID for dedup
            article_id = str(article.get("id", ""))
            if not article_id or self._is_seen(article_id):
                continue

            # Parse fields
            title = article.get("title", "").strip()
            summary = article.get("description", "").strip()
            url = article.get("url", "")
            published = article.get("publishedAt", "")

            if not title:
                continue

            # Parse date to IST datetime
            dt = parse_iso_datetime(published)

            # Build standard item using base class helper
            new_items.append(self._build_item(dt, title, summary, url))
            new_ids.append(article_id)

        # Bulk mark as seen
        self._mark_seen_bulk(new_ids)
        return new_items
```

## Step 2: Register in `sites.yaml`

Add an entry (key must match the `name` attribute):

```yaml
sources:
  my_source:
    enabled: true
    display_name: "My Source"
    poll_interval: [5, 10]    # seconds [min, max]
    use_proxy: false
    description: "Description of this news source"
```

## Step 3: Restart

```bash
python main.py
```

The orchestrator auto-discovers the new scraper and starts it.

---

## BaseScraper API Reference

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Unique identifier (must match sites.yaml key) |
| `session` | `requests.Session` | Pre-configured HTTP session |
| `config` | `dict` | Merged global + site config |

### Methods You Implement

| Method | Required | Description |
|--------|----------|-------------|
| `setup()` | No | One-time init (headers, state variables) |
| `fetch_news()` | **Yes** | Return list of new news item dicts |

### Helper Methods (from BaseScraper)

| Method | Description |
|--------|-------------|
| `self._is_seen(id)` | Check if ID was already processed |
| `self._mark_seen(id)` | Mark single ID as seen |
| `self._mark_seen_bulk([ids])` | Mark multiple IDs as seen |
| `self._build_item(dt, caption, summary, url)` | Build standard news item dict |
| `self._safe_get(url, **kwargs)` | GET with error handling (returns None on failure) |
| `self.clean_html(text)` | Strip HTML tags from text |

### `_build_item()` Output Format

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

### Available Date Parsers (`utils/time_utils.py`)

| Function | Input Format | Example |
|----------|-------------|---------|
| `parse_iso_datetime(s)` | ISO 8601 / `Z` suffix | `2026-03-09T10:30:00Z` |
| `parse_rss_date(s)` | RFC 2822 (RSS pubDate) | `Sun, 09 Mar 2026 10:30:00 +0530` |
| `parse_timestamp(ts)` | Unix timestamp (int) | `1741502400` |
| `parse_groww_date(s)` | Groww format (assumed UTC) | `2026-03-09T10:30:00` |
| `parse_zerodha_date(s)` | Zerodha title format | `10:30 AM, 09 Mar 2026` |
| `parse_stockedge_datetime(d, t)` | StockEdge Date+Time | `2026-03-09T00:00:00` + `03:45 pm` |
| `parse_angelone_date(s)` | Angel One date | `9 March 2026` |

All return `datetime | None` in IST timezone. Pass the result to `_build_item()`.

---

## Scraping Strategy Tips

| Source Type | Approach | Example |
|-------------|----------|---------|
| **JSON API** | Best — fast, structured, low bandwidth | Groww, TradingView |
| **RSS Feed** | Good — standard format, easy parsing | LiveMint RSS |
| **HTML scrape** | Last resort — brittle, higher bandwidth | Zerodha Pulse |
| **Angular/React SSR** | Parse embedded JSON state | ScanX (ng-state) |
| **ETag caching** | Add `If-None-Match` header → 304 saves bandwidth | ScanX |

## Dashboard Integration

New sources automatically appear in the dashboard — no frontend changes needed.
The source badge color defaults to the accent color. To add a custom color,
add a CSS rule in `dashboard/style.css`:

```css
.source-my_source { background: rgba(255, 100, 0, 0.15); color: #ff6400; }
```
