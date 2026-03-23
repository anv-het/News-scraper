# News Scrapper — Existing Sources Deep Dive

Detailed documentation for each implemented scraper: how it works,
what data it fetches, rate limits, and known quirks.

---

## 1. Groww (`sites_scrapers/groww.py`)

### Source
- **Website**: https://groww.in/market-news/stocks
- **API**: `https://groww.in/v2/api/feed/public?page=0&publisherId=stocknewssummary&size=200`

### How It Works
1. Polls the Groww public feed API which returns up to 200 stock news items
2. Each item has a unique `postId` used for deduplication
3. Dates arrive in UTC format `2026-03-08T10:57:03` → converted to IST
4. News URLs extracted from `data.cta[0].ctaUrl` field

### Data Quality
- **Caption**: Always available (article title)
- **Summary**: Available (article body)
- **URL**: Sometimes empty (not all items have CTAs)
- **Dates**: UTC, consistent format

### Rate Limits
- No known rate limiting on the public API
- Poll interval: 5-8 seconds (safe)

### Headers Required
```
x-platform: web
x-device-type: desktop
Referer: https://groww.in/market-news/stocks
```

---

## 2. LiveMint (`sites_scrapers/livemint.py`)

### Source
- **Website**: https://www.livemint.com/latest-news
- **API**: `https://www.livemint.com/api/cms/story/latest?limit=10`
- **RSS**: 9 category feeds

### How It Works — Dual Strategy
1. **Fast path (every poll cycle)**: JSON API returns the 10 latest articles
2. **Slow path (rotated)**: 9 RSS feeds cycled one per poll, full sweep ~45 seconds
   - `/rss/news`, `/rss/companies`, `/rss/markets`, `/rss/industry`
   - `/rss/politics`, `/rss/opinion`, `/rss/money`, `/rss/budget`, `/rss/elections`

### Why Dual?
- API is fastest for breaking news (10 most recent)
- RSS covers all categories including older articles the API may skip
- Combined: near-complete coverage of LiveMint content

### Data Quality
- **Caption**: Always available
- **Summary**: Available from both API and RSS
- **URL**: Full article URLs
- **Dates**: ISO 8601 (API) and RFC 2822 (RSS)

### Rate Limits
- Moderate — API is lightweight JSON, RSS is standard
- Poll interval: 3-5 seconds for API, ~5s per RSS feed

### Special Handling
- HTML entities in summaries stripped via `clean_html()`
- RSS date parsing handles `+0530` timezone offsets

---

## 3. ScanX (`sites_scrapers/scanx.py`)

### Source
- **Website**: https://scanx.trade/stock-market-news
- **Method**: Angular SSR page with embedded JSON state

### How It Works
1. Fetches the full HTML page
2. Extracts `<script id="ng-state">` JSON blob (Angular transfer state)
3. Decodes Angular HTML entities: `&q;` → `"`, `&l;` → `<`, etc.
4. Parses `sections_data[].articles[]` from the decoded JSON
5. Uses **ETag caching**: sends `If-None-Match` header → 304 means no change

### Why ETag?
- The page ISR (Incremental Static Regeneration) cache revalidates ~every 60s
- Most polls return 304 (1-2 KB response) instead of full page (~200 KB)
- Saves >99% bandwidth on quiet periods

### Data Quality
- **Caption**: `articletitle` field
- **Summary**: Available
- **URL**: Constructed from `subcategory` + `slug` + `id`
- **Dates**: ISO 8601 with Z suffix

### URL Construction
Maps subcategories to URL slugs:
```
corporate_action → corporate-actions
normal_news → stocks
order&deals → orders-deals
results → earnings
```

### Rate Limits
- Standard web scraping limits
- Poll interval: 8-12 seconds (ETag makes most requests cheap)

---

## 4. TradingView (`sites_scrapers/tradingview.py`)

### Source
- **Website**: https://in.tradingview.com/news-flow
- **API 1**: India-specific (`market_country=IN` + `lang=en_IN`)
- **API 2**: General English-India (`lang=en_IN` only)

### How It Works
1. Fetches **both** API endpoints each poll cycle with cache-bust timestamps
2. Uses `streaming=true` and `client=screener` for more real-time data
3. API 1 returns India market-specific news
4. API 2 returns broader English-India news (overlaps slightly)
5. Each article has a unique `id` field for deduplication
6. Dates arrive as Unix timestamps → converted to IST

### Why Two APIs?
- ~85% unique content between them
- India-specific catches market-focused stories
- General catches broader financial/economic news
- `streaming=true` + `client=screener` returns fresher data than `client=web`

### Data Quality
- **Caption**: Always available (article title)
- **Summary**: Usually empty (API doesn't provide descriptions)
- **URL**: `link` field or constructed from `storyPath`
- **Dates**: Unix timestamps, precise

### Rate Limits
- TradingView is generally lenient for their news API
- Poll interval: 2-4 seconds

### Headers Required
```
Referer: https://in.tradingview.com/
Origin: https://in.tradingview.com
```

---

## 5. Zerodha Pulse (`sites_scrapers/zerodha.py`)

### Source
- **Website**: https://pulse.zerodha.com/
- **Method**: HTML scraping with BeautifulSoup

### How It Works
1. Fetches the main page HTML
2. Parses `li.box.item` elements for main articles
3. Also extracts `ul.similar > li` for related/similar articles
4. Date extracted from `span.date[title]` attribute (e.g., `08:38 AM, 07 Mar 2026`)
5. Deduplicates by article URL (href)

### What It Extracts
- **Main articles**: Title (`h2.title > a`), description (`div.desc`), date, URL
- **Similar articles**: Title (`a.title2`), date only (no description)

### Data Quality
- **Caption**: Always available
- **Summary**: Available for main articles only, empty for similar
- **URL**: External article URLs (links to original source)
- **Dates**: Zerodha's own format from title attribute

### Rate Limits
- Standard web scraping — not aggressive
- Poll interval: 8-12 seconds
- Uses proper browser-like headers to avoid blocks

### Headers Required
```
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "Windows"
sec-fetch-dest: document
sec-fetch-mode: navigate
upgrade-insecure-requests: 1
```

---

## 6. StockEdge (`sites_scrapers/stockedge.py`)

### Source
- **Website**: https://web.stockedge.com/daily-updates?section=news
- **API**: `https://api.stockedge.com/Api/DailyDashboardApi/GetLatestNewsItems?page=1&pageSize=20&sectionType=null&lang=en`

### How It Works
1. Polls the StockEdge Daily Dashboard API (JSON list)
2. Each item has a unique numeric `ID` field for deduplication
3. Caption from `Description`, summary from `Details` (HTML stripped)
4. Dates from `Date` + `Time` fields (e.g. `2026-03-09T00:00:00` + `03:45 pm`)

### Data Quality
- **Caption**: Always available (`Description` field)
- **Summary**: Available (`Details`, HTML tags stripped)
- **URL**: N/A — StockEdge doesn't provide article URLs
- **Dates**: IST, combined from Date + Time strings

### Rate Limits
- API may silently return empty results when blocked (no 403/429)
- Poll interval: 5-10 seconds

---

## 7. MoneyControl (`sites_scrapers/moneycontrol.py`)

### Source
- **Website**: https://www.moneycontrol.com/news/business/markets/
- **Method**: HTML scraping with BeautifulSoup

### How It Works
1. Fetches the markets news listing page
2. Parses `<ul id="cagetory">` (their actual HTML typo) → `<li class="clearfix">`
3. Extracts title from `<a title="">`, URL from `<a href="">`
4. Summary from first non-empty `<p>` in each item
5. Article ID extracted from URL trailing number (e.g. `-13855013.html` → `13855013`)

### Data Quality
- **Caption**: Always available
- **Summary**: Available (first paragraph)
- **URL**: Full article URLs
- **Dates**: Not available in listing — uses scrape time

### Rate Limits
- Standard HTML scraping
- Poll interval: 5-10 seconds

### Notes
- RSS feeds (`/rss/latestnews.xml`) are stale since August 2024
- No JSON API found — HTML scraping is the only reliable method

---

## 8. Angel One (`sites_scrapers/angelone.py`)

### Source
- **Website**: https://www.angelone.in/news/market-updates
- **Method**: HTML scraping with BeautifulSoup (Next.js SSR page)

### How It Works
1. Fetches the market updates page (server-side rendered)
2. Parses `<div class="kgEtrD">` cards
3. Title from `<h2 class="entry-title"><a>`, URL from the same `<a href>`
4. Date from `<span>` text (e.g. "9 March 2026")
5. Deduplicates by URL slug (last path segment)

### Data Quality
- **Caption**: Always available
- **Summary**: Not available in listing page
- **URL**: Full article URLs
- **Dates**: Day-level precision only ("9 March 2026")

### Rate Limits
- Cloudflare-protected; occasional bot challenges cause intermittent blocks
- Poll interval: 5-10 seconds

---

## Source Comparison

| Feature | Groww | LiveMint | ScanX | TradingView | Zerodha | StockEdge | MoneyControl | Angel One |
|---------|-------|----------|-------|-------------|---------|-----------|--------------|-----------|
| Method | API | API+RSS | HTML+ETag | API×2 | HTML | API | HTML | HTML |
| Volume/day | ~200 | ~300+ | ~50 | ~400+ | ~150 | ~20 | ~25 | ~10 |
| Has summary | ✅ | ✅ | ✅ | ❌ | Partial | ✅ | ✅ | ❌ |
| Latency | Low | Low | Medium | Low | Medium | Low | Medium | Medium |
| Bandwidth | Low | Medium | Low (ETag) | Low | High | Low | Medium | Medium |
| Reliability | High | High | High | High | Medium | Low | High | Low |
