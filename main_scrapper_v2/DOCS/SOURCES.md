# News Scrapper — Sources Deep Dive (Current)

Updated: 2026-04-22

This file now reflects all currently implemented sources in `sites_scrapers/` and their
current runtime status from `sites.yaml`.

## Current Source Inventory

| Source Key | Display Name | Status | Poll Interval (s) | Method | Main Dedup Key |
|---|---|---|---|---|---|
| groww | Groww | Enabled | 2-4 | JSON API | `postId` |
| livemint | LiveMint | Enabled | 2-3 | API + RSS rotation | `news_url` |
| scanx | ScanX | Enabled | 3-5 | HTML + Angular state + ETag | `article_id` |
| tradingview | TradingView | Enabled | 2-4 | Dual JSON API | `news_id` |
| moneycontrol | MoneyControl | Enabled | 5-10 | HTML scrape | `article_id` from URL |
| cnbctv18 | CNBC TV18 | Enabled | 5-10 | JSON API | `story_id` |
| reuters | Reuters | Enabled | 8-15 | Arc XML sitemap | `news_url` |
| cnbc | CNBC | Enabled | 8-15 | RSS primary, HTML fallback | `news_url` |
| bbc | BBC News | Enabled | 8-15 | RSS rotation | `news_url` |
| economictimes | Economic Times | Enabled | 3-6 | HTML primary, RSS fallback | `msid` |
| zeebusiness | Zee Business | Enabled | 8-15 | Sitemap primary, `__NEXT_DATA__` fallback | `news_url` |
| etnow | ET Now | Enabled | 5-25 | API primary, sitemap fallback | no explicit `_is_seen` mark in scraper |
| businessstandard | Business Standard | Enabled | 5-10 | `__NEXT_DATA__` primary, HTML fallback | `article_id` |
| ndtv | NDTV | Enabled | 3-6 | RSS primary, HTML fallback | `news_url` |
| timesofindia | Times of India | Enabled | 5-10 | HTML pattern scrape | `article_id` |
| zerodha | Zerodha Pulse | Disabled | 3-5 | HTML scrape | `news_url` |
| stockedge | StockEdge | Disabled | 1-2 | JSON API (3 pages) | `ID` |
| angelone | Angel One | Disabled | 5-8 | API + sitemap | `slug` |
| rediff | Rediff | Disabled | 5-10 | HTML + RSS merge | `news_url` |

## Enabled Sources (Production)

### 1. Groww (`sites_scrapers/groww.py`)
- Website: https://groww.in/market-news/stocks
- API: `https://groww.in/v2/api/feed/public?page=0&publisherId=stocknewssummary&size=20`
- Method: JSON API polling with cache-bust (`&_ts=`)
- Dedup: `postId`
- Date parsing: `parse_groww_date` (UTC to IST)
- Notes: session refresh every 24h; URL from `data.cta[0].ctaUrl`; image from `images`/`imageUrl`

### 2. LiveMint (`sites_scrapers/livemint.py`)
- Website: https://www.livemint.com/latest-news
- API: `https://www.livemint.com/api/cms/story/latest?limit=50`
- RSS feeds: news, companies, markets, industry, politics, opinion, money, budget, elections
- Method: fast API + rotated RSS feed coverage
- Dedup: article URL
- Date parsing: `parse_iso_datetime` (API), `parse_rss_date` (RSS)
- Notes: RSS sweep interval controlled by `RSS_INTERVAL = 18`

### 3. ScanX (`sites_scrapers/scanx.py`)
- Website: https://scanx.trade/stock-market-news
- Method: HTML fetch, parse `<script id="ng-state">`, decode custom entities, extract `sections_data`
- Dedup: article `id`
- Date parsing: `parse_iso_datetime`
- Notes: uses ETag (`If-None-Match`) and skips processing on HTTP 304

### 4. TradingView (`sites_scrapers/tradingview.py`)
- Website: https://in.tradingview.com/news-flow
- APIs:
   - `...news-flow/v2/news?filter=lang%3Aen_IN&filter=market_country%3AIN&client=screener&streaming=true&user_prostatus=non_pro`
   - `...news-flow/v2/news?filter=lang%3Aen_IN&client=screener&streaming=true&user_prostatus=non_pro`
- Method: dual endpoint fetch every cycle
- Dedup: `id`
- Date parsing: `parse_timestamp`
- Notes: URL from `link` or `storyPath`

### 5. MoneyControl (`sites_scrapers/moneycontrol.py`)
- Website: https://www.moneycontrol.com/news/business/markets/
- Method: HTML scraping of `<ul id="cagetory">` list
- Dedup: numeric ID extracted from URL tail
- Date handling: no per-item timestamp on listing, uses `now_ist()`
- Notes: session refresh every 24h

### 6. CNBC TV18 (`sites_scrapers/cnbctv18.py`)
- Website: https://www.cnbctv18.com/
- API: `https://api-en.cnbctv18.com/nodeapi/v1/cne/get-article-list?count=50&offset=0...`
- Method: JSON API with flexible response-key handling (`data`/`articles`/`result`/`items`/`rows`)
- Dedup: `story_id`
- Date parsing: `parse_iso_datetime` (`created_at`/`updated_at`)

### 7. Reuters (`sites_scrapers/reuters.py`)
- Website: https://www.reuters.com/
- Sitemap: `https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml`
- Method: Arc outbound sitemap, rotates pages (`from=0/100/200`)
- Dedup: article URL
- Date parsing: `parse_iso_datetime`
- Notes: uses sitemap namespaces and image extraction from `image:image`

### 8. CNBC (`sites_scrapers/cnbc.py`)
- Website: https://www.cnbc.com/world-markets/
- RSS: `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114`
- Method: RSS primary, `window.__s_data` fallback
- Dedup: article URL
- Date parsing: `parse_rss_date` (RSS), `parse_iso_datetime` (fallback assets)
- Notes: skips `/video/` and `/select/`

### 9. BBC News (`sites_scrapers/bbc.py`)
- Website: https://www.bbc.com/news
- RSS feeds:
   - https://feeds.bbci.co.uk/news/rss.xml
   - https://feeds.bbci.co.uk/news/world/rss.xml
   - https://feeds.bbci.co.uk/news/business/rss.xml
- Method: rotates one feed per cycle
- Dedup: article URL
- Date parsing: `parse_rss_date`
- Notes: image extraction from `media:thumbnail` and `media:content`

### 10. Economic Times (`sites_scrapers/economictimes.py`)
- Website: https://economictimes.indiatimes.com/markets/stocks/news
- HTML pages:
   - `/markets/stocks/news`
   - `/markets/stocks/earnings`
   - `/markets`
- RSS fallback feeds (5): top stories, markets, stocks, economy, industry
- Method: HTML first, parallel RSS fallback
- Dedup: `msid` extracted from URL pattern
- Date parsing: `parse_iso_datetime` (HTML time tags), `parse_rss_date` (RSS)

### 11. Zee Business (`sites_scrapers/zeebusiness.py`)
- Website: https://www.zeebiz.com/
- Sitemap: `https://www.zeebiz.com/news-sitemap.xml`
- Method: sitemap primary, homepage `__NEXT_DATA__` fallback
- Dedup: article URL
- Date parsing: `parse_iso_datetime` or timestamp parsing from `created`
- Notes: includes malformed-XML fixer and regex extraction fallback

### 12. ET Now (`sites_scrapers/etnow.py`)
- Website: https://www.etnownews.com/
- API: `https://api.etnownews.com/api/latest?seopath=latest-news&pageno=1&itemcount=41&origin=desktop&channel_id=382`
- Sitemap fallback: `https://www.etnownews.com/feeds/google-news-sitemap-etnow.xml`
- Method: API primary, sitemap fallback
- Dedup note: scraper currently does not call `_is_seen`/`_mark_seen_bulk` in this file
- Date parsing: `parse_timestamp` and `parse_iso_datetime`

### 13. Business Standard (`sites_scrapers/businessstandard.py`)
- Website: https://www.business-standard.com/latest-news
- Method: parse Next.js `__NEXT_DATA__` (`props.pageProps.newsData`) with HTML fallback
- Dedup: `article_id` (fallback uses URL)
- Date parsing: `parse_timestamp` on `published_date`

### 14. NDTV (`sites_scrapers/ndtv.py`)
- Website: https://www.ndtv.com/latest
- RSS: `https://feeds.feedburner.com/ndtvnews-latest`
- Method: FeedBurner RSS primary, HTML fallback
- Dedup: article URL
- Date parsing: `parse_rss_date`; HTML fallback parses NDTV date strings
- Notes: skips video/photos/topic URLs in fallback path

### 15. Times of India (`sites_scrapers/timesofindia.py`)
- Website: https://timesofindia.indiatimes.com
- Method: homepage HTML scan for `/articleshow/{id}.cms` links
- Dedup: article ID extracted from URL
- Date handling: uses scrape time (`now_ist`) because homepage does not expose per-item times
- Notes: image from `msid` attribute or constructed TOI CDN URL

## Disabled Sources (Implemented, Currently Off)

### Zerodha Pulse (`sites_scrapers/zerodha.py`)
- Status: disabled in `sites.yaml`
- Method: HTML parsing of `li.box.item` plus `ul.similar > li`
- Dedup: article URL
- Date parsing: `parse_zerodha_date`

### StockEdge (`sites_scrapers/stockedge.py`)
- Status: disabled in `sites.yaml`
- Method: JSON API paging across pages `[1, 2, 3]`
- API: `https://api.stockedge.com/Api/DailyDashboardApi/GetLatestNewsItems?page={page}&pageSize=20&sectionType=null&lang=en`
- Dedup: numeric `ID`
- Date parsing: `parse_stockedge_datetime`
- Notes: adds random delay between page fetches

### Angel One (`sites_scrapers/angelone.py`)
- Status: disabled in `sites.yaml`
- Method: blog API primary + sitemap secondary
- APIs:
   - `https://kp-hl-httpapi-prod.angelone.in/public/v2/blog?offset=0&limit=20`
   - `https://www.angelone.in/news-sitemap.xml`
- Dedup: slug
- Date parsing: `parse_iso_datetime`
- Notes: category whitelist and hourly session refresh

### Rediff (`sites_scrapers/rediff.py`)
- Status: disabled in `sites.yaml`
- Method: HTML article/image mapping merged with RSS metadata
- Endpoints:
   - `https://www.rediff.com/news`
   - `https://www.rediff.com/rss/newsrss.xml`
- Dedup: article URL
- Date parsing: `parse_rss_date` or fallback `now_ist`

## Notes

- Active sources in config: 15
- Disabled sources in config: 4
- Total implemented source scrapers: 19 (`sites_scrapers/base.py` is abstract and not a source)
- This document intentionally avoids speculative throughput metrics and only records behavior visible in code/config.
