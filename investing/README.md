# Investing.com India Equities & News Scraper

A professional-grade scraper for fetching Indian equity listings and news from Investing.com.

## Features

- **Equities Fetcher**: Downloads complete list of Indian equities (~7500+ stocks) via API
- **News Scraper**: Scrapes news articles for each equity with pagination support
- **Rate Limiting**: Configurable delays between requests to avoid detection
- **Batch Processing**: Long breaks after processing batches of equities
- **Resume Support**: Skip already scraped equities
- **Scheduled Mode**: Cron-style scheduling with time windows and day gaps
- **Professional Logging**: Configurable log levels with file output

## Project Structure

```
investing/
├── main.py              # Main entry point with CLI
├── config.py            # Configuration management
├── logger.py            # Logging setup
├── fetch_equities.py    # Equities API fetcher
├── fetch_news.py        # News scraper
├── requirements.txt     # Python dependencies
├── .env                 # Configuration (copy from .env.example)
├── .env.example         # Configuration template
├── output/              # Output directory
│   ├── equities_india_latest.json
│   ├── json/            # News JSON files per equity
│   └── csv/             # News CSV files per equity
└── logs/                # Log files
```

## Installation

### Windows

1. **Create virtual environment**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure settings**:
   ```bash
   copy .env.example .env
   # Edit .env as needed
   ```

### Ubuntu/Linux

1. **Install system dependencies** (required for curl_cffi):
   ```bash
   sudo apt update
   sudo apt install -y python3-pip python3-venv libcurl4-openssl-dev libssl-dev
   ```

2. **Create virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure settings**:
   ```bash
   cp .env.example .env
   # Edit .env as needed (relative paths work on both Windows and Ubuntu)
   ```

### macOS

1. **Install system dependencies**:
   ```bash
   brew install openssl curl
   ```

2. **Create virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure settings**:
   ```bash
   cp .env.example .env
   ```

## Usage

### One-Time Run

```bash
# Full run (equities + news)
python main.py

# Fetch equities only
python main.py --equities-only

# Scrape news only (uses existing equities JSON)
python main.py --news-only

# Test mode (limited equities)
python main.py --test

# Debug logging
python main.py --debug
```

### Scheduled/Cron Mode

```bash
# Run in scheduled mode
python main.py --scheduled
```

Or set `CRON_ENABLED=true` in `.env` and run `python main.py`.

In scheduled mode, the scraper will:
1. Wait until the time window opens (default: 9:00-22:00)
2. Add a random delay before starting (configurable)
3. Run the full scraping cycle
4. Wait for the next scheduled day (based on `CRON_DAYS_GAP`)

### Individual Modules

```bash
# Run equities fetcher directly
python fetch_equities.py

# Run news scraper directly
python fetch_news.py
```

## Configuration

All settings can be configured via `.env` file or environment variables.

### Path/Output Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `OUTPUT_DIR` | `./output` | Base output directory |
| `JSON_OUTPUT_DIR` | `./output/json` | News JSON output directory |
| `CSV_OUTPUT_DIR` | `./output/csv` | News CSV output directory |
| `EQUITIES_JSON` | `./output/equities_india_latest.json` | Equities JSON path |
| `LOG_DIR` | `./logs` | Log files directory |
| `ENABLE_CSV_OUTPUT` | `true` | Enable CSV output in addition to JSON |

### Delay Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PAGE_DELAY_MIN` | `2` | Min delay between news pages (seconds) |
| `PAGE_DELAY_MAX` | `5` | Max delay between news pages (seconds) |
| `EQUITY_DELAY_MIN` | `3` | Min delay between equities (seconds) |
| `EQUITY_DELAY_MAX` | `8` | Max delay between equities (seconds) |
| `BATCH_SIZE` | `50` | Take long break after this many equities |
| `BREAK_MIN_MINUTES` | `5` | Min break duration (minutes) |
| `BREAK_MAX_MINUTES` | `15` | Max break duration (minutes) |
| `REQUEST_TIMEOUT` | `60` | HTTP request timeout (seconds) |

### Scraper Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_PAGES_PER_EQUITY` | `100` | Max news pages per equity |
| `TEST_MODE` | `false` | Limit equities for testing |
| `TEST_LIMIT` | `5` | Number of equities in test mode |
| `SKIP_EXISTING` | `true` | Skip already scraped equities |

### Cron/Scheduling Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `CRON_ENABLED` | `false` | Enable scheduled mode |
| `CRON_START_HOUR` | `9` | Start of allowed time window (24h) |
| `CRON_END_HOUR` | `22` | End of allowed time window (24h) |
| `CRON_DAYS_GAP` | `1` | Days between runs (0 = daily) |
| `CRON_RANDOM_START_DELAY_MAX` | `30` | Max random delay before start (minutes) |

### Logging Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Log level (DEBUG/INFO/WARNING/ERROR) |
| `LOG_TO_FILE` | `true` | Also save logs to file |

### MongoDB Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_ENABLED` | `false` | Enable MongoDB storage |
| `MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection URL |
| `MONGODB_DATABASE` | `investing_scraper` | Database name |
| `MONGODB_EQUITIES_COLLECTION` | `equities` | Collection for equities |
| `MONGODB_NEWS_COLLECTION` | `news` | Collection for news |

MongoDB storage works **in addition** to JSON files - both are saved when enabled.

## Output Format

### Equities JSON

```json
{
  "data": [
    {
      "Id": "7310",
      "Name": "Aditya Birla Capital",
      "Symbol": "ADTB",
      "Url": "/equities/aditya-birla"
    }
  ]
}
```

### News JSON

```json
{
  "equity_id": "7310",
  "equity_name": "Aditya Birla Capital",
  "equity_symbol": "ADTB",
  "equity_url": "/equities/aditya-birla",
  "fetched_at": "2026-02-09T12:00:00",
  "total_articles": 50,
  "articles": [
    {
      "title": "Article Title",
      "link": "https://in.investing.com/news/...",
      "description": "Article description...",
      "source": "Reuters",
      "source_url": "https://in.investing.com/brokers/",
      "date": "2026-02-09 10:30:00",
      "date_display": "09 Feb 2026"
    }
  ]
}
```

### News CSV

Each CSV file contains one row per article with these columns:

| Column | Description |
|--------|-------------|
| `equity_id` | Equity ID from the API |
| `equity_name` | Company name |
| `equity_symbol` | Stock symbol |
| `equity_url` | URL path for the equity |
| `title` | Article title |
| `link` | Full URL to the article |
| `description` | Article description/summary |
| `source` | News source name |
| `source_url` | Source URL |
| `date` | Article datetime (ISO format) |
| `date_display` | Human-readable date |
| `fetched_at` | When the article was scraped |

## Dependencies

- `curl_cffi` - HTTP client with TLS fingerprinting
- `beautifulsoup4` - HTML parsing
- `lxml` - Fast HTML parser
- `python-dotenv` - Environment variable loading
- `pymongo` - MongoDB driver (optional, for MongoDB storage)
- `cloudscraper` (fallback) - Cloudflare bypass

## Notes

- The scraper uses `curl_cffi` with Chrome impersonation to bypass bot detection
- Random delays are used between all requests to appear more human-like
- Long breaks are taken after processing batches to avoid rate limiting
- Existing news files are skipped by default (set `SKIP_EXISTING=false` to re-scrape)

## License

MIT License
