# News Scrapper — Proxy & Anti-Block Guide

How to configure and use proxies, avoid blocks, and handle bot protection.

---

## Proxy Configuration

### Enable Proxies

In `.env`:
```
PROXY_ENABLED=true
PROXY_FILE=proxies.txt
PROXY_BANDWIDTH_LIMIT_MB=1024
PROXY_ROTATION=round_robin
```

### Proxy File Format

`proxies.txt` — one proxy per line:
```
# Comments start with #
host:port:username:password
```

Supports:
- Bright Data residential proxies
- Standard datacenter proxies
- Any HTTP/HTTPS proxy with basic auth

### Per-Source Proxy Control

In `sites.yaml`, enable proxy per source:
```yaml
sources:
  groww:
    use_proxy: true     # route through proxy pool
  livemint:
    use_proxy: false    # direct connection
```

---

## Rotation Strategies

### Round-Robin (default)
```
PROXY_ROTATION=round_robin
```
Each request uses the next proxy in order: P1 → P2 → P3 → P1 → ...

### Random
```
PROXY_ROTATION=random
```
Each request picks a random available proxy.

---

## Bandwidth Management

### Tracking
Each proxy tracks bytes used. When a proxy hits its bandwidth limit, it's automatically disabled.

### Persistence
If Redis is enabled, bandwidth counters are stored in Redis and survive restarts:
```
news_scrapper:proxy:bw:1.2.3.4:8080 → "524288000"  (500 MB used)
```

### Limits
Default: 1024 MB (1 GB) per proxy per month.
Configure in `.env`:
```
PROXY_BANDWIDTH_LIMIT_MB=1024
```

### Monitoring
Check proxy status via Redis:
```bash
redis-cli keys "news_scrapper:proxy:bw:*"
```

---

## Anti-Block Strategies

### Built-In Protections

| Strategy | Implementation |
|----------|---------------|
| **Realistic User-Agent** | Chrome 145 on Windows 10 |
| **Proper Referer headers** | Each scraper sets its site's referer |
| **Browser-like headers** | Accept, Accept-Language, Accept-Encoding |
| **Randomized intervals** | Never predictable polling patterns |
| **ETag caching** | Reduces request volume (ScanX) |
| **Gradual backoff** | Exponential wait on errors |

### If a Site Detects Bot Traffic

Symptoms:
- 403 Forbidden responses
- 429 Too Many Requests
- Empty responses / captcha pages
- Cloudflare challenge pages

Solutions (in order of preference):

1. **Increase poll interval**:
   ```yaml
   groww:
     poll_interval: [15, 25]  # slower but safer
   ```

2. **Enable proxies** for that source:
   ```yaml
   groww:
     use_proxy: true
   ```

3. **Rotate User-Agents**: Add to scraper's `setup()`:
   ```python
   import random
   UAS = [
       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
       "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ...",
   ]
   self.session.headers["User-Agent"] = random.choice(UAS)
   ```

4. **Add session management**: If the site needs cookies/sessions,
   do an initial page load in `setup()` to get cookies.

### Captcha / Cloudflare Handling

If a source uses Cloudflare or similar bot protection:

1. The scraper will start getting errors → enters **degraded** state
2. After `BLOCKED_THRESHOLD_MINUTES`, enters **blocked** state
3. Logged to `blocked.log`
4. Auto-retries every `BLOCKED_RETRY_MINUTES`

For persistent Cloudflare challenges, options:
- Use residential proxies (Bright Data) which have better fingerprints
- Use a headless browser approach (would require modifying the scraper to use Selenium/Playwright)
- Switch to an alternative endpoint (API/RSS instead of HTML)

---

## Current Proxy Inventory

### Bright Data (15 proxies)
- Type: Residential
- Bandwidth: 1 GB per IP per month
- Response time: 0.85–4.1 seconds
- Format: `brd.superproxy.io:33335:brd-customer-...:password`

### Datacenter (10 proxies)
- Type: Datacenter
- Bandwidth: 1 GB per IP per month
- Format: `host:port:user:pass`

### Total Monthly Bandwidth
- 15 × 1 GB = 15 GB (Bright Data)
- 10 × 1 GB = 10 GB (Datacenter)
- **Total: 25 GB/month**

### Estimated Usage
- Each news API call: ~5-50 KB
- Each HTML scrape: ~100-300 KB
- At 5 sources × ~10 requests/min: ~3-15 GB/month
- Well within budget for most configurations
