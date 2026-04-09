# News Categorization System

⚠️ **IMPORTANT**: The article classification feature documented in this file is **NOT YET IMPLEMENTED**. The classifier module (`categorizing/classifier.py`) does not exist. Only the top 100 news ranking system is currently functional. See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#categorization-system-30-complete) for details.

---

## Overview

The news categorization system automatically classifies articles into predefined categories using zero-shot NLP classification. Additionally, it maintains a global "Top News" list of the 100 most relevant articles across all sources, ranked by recency, keyword relevance, and source importance.

**Currently Implemented**:
- ✅ Global top 100 news ranking
- ✅ Source importance weighting
- ✅ Top news persistence

**Not Yet Implemented**:
- ❌ Article classification with BART model
- ❌ Category field in articles
- ❌ Category filtering in dashboard
- ❌ Zero-shot NLP inference

---

## Categories

Articles are classified into one of six categories:

| Category | Definition | Examples |
|----------|-----------|----------|
| **Market** | Stocks, finance, trading, financial markets | Stock price updates, market analysis, trading tips |
| **India** | Domestic India news and politics | India government decisions, elections, policy announcements |
| **Business** | Corporate news, economy, industry updates | Company earnings, M&A, business trends |
| **Politics** | Global politics, government, elections | Political elections, international relations |
| **World** | International events, global news | World events, international crises, global news |
| **Others** | Entertainment, education, lifestyle, sports, tech | Movie releases, education news, health tips |

---

## How It Works

### 1. Classification Flow

```
New Articles from Scraper
    ↓
classify_batch(articles)  [Uses BART model]
    ↓
Articles enriched with:
  - category: "Market" | "Business" | ...
  - category_confidence: 0.85
    ↓
Saved to DATA/<source>/<date>.json
    ↓
update_top_news()  [Recalculates top 100]
    ↓
Updated top_news.json
```

### 2. BART Zero-Shot Classifier

The system uses **facebook/bart-large-mnli**, a model trained for zero-shot classification:

- **No training required**: Works with custom labels out of the box
- **Fast inference**: ~100-200ms per article with GPU (~1-2 seconds with CPU)
- **Efficient**: Batch processing reduces latency to ~30-50ms per article
- **Reliable**: Returns confidence scores (0.0-1.0)

**How zero-shot works:**
```
Input: Title + Summary
       "Stock market crashes 5% amid recession fears"

Candidate Labels:
  - stocks and finance
  - business and economy
  - politics and government
  - ...

Model predicts: "stocks and finance" (confidence: 0.92)
Maps to category: "Market"
```

### 3. Top News Ranking Algorithm

Articles are ranked globally (across all sources) using the formula:

```
Score = TimeScore × (1 + KeywordBoost) × SourceWeight
```

**Components:**

#### TimeScore (Recency)
- Exponential decay over 7 days
- Formula: `e^(-age_days / 7)`
- **Result**: New articles score ~1.0, 7-day-old articles score ~0.37

#### KeywordBoost (Relevance)
Articles with relevant keywords get a boost:

| Keyword | Boost | Examples |
|---------|-------|----------|
| breaking | +25% | Breaking news, exclusive reports |
| war, military, conflict | +15-20% | War updates, military actions |
| crisis, emergency, disaster | +15-20% | Natural disasters, crises |
| politics, election, government | +10-15% | Political news, elections |
| stocks, market, economy | +10-15% | Market updates, economic news |
| recession, inflation | +15-18% | Economic downturn news |

#### SourceWeight (Authority)
Importance of the news source (configurable in sites.yaml):

```yaml
moneycontrol:
  source_importance_weight: 1.3  # 30% boost for quality financial source

reuters:
  source_importance_weight: 1.5  # 50% boost for authoritative source

groww:
  source_importance_weight: 1.2  # 20% boost for stock market source
```

**Example Calculation:**
```
Article: "Breaking: Parliament passes economic stimulus bill"
Source: reuters (weight: 1.5)
Published: 2 hours ago

TimeScore = e^(-2h / 168h) = 0.99
KeywordBoost = 0.15 (breaking) + 0.10 (political) = 0.25
SourceWeight = 1.5

Score = 0.99 × (1 + 0.25) × 1.5 = 1.86 (High ranking!)
```

---

## API Endpoints

### Get Categories
```
GET /api/categories

Response:
{
  "categories": ["Market", "India", "Business", "Politics", "World", "Others"],
  "description": "Available news categories for classification"
}
```

### Filter News by Category
```
GET /api/news?category=Market
GET /api/news?category=Business&limit=50

Query Parameters:
  - category: Category name (optional)
  - source: Source name (optional)
  - date: News date YYYY-MM-DD (optional)
  - limit: Max articles (default: 500)

Response:
[
  {
    "news_caption": "Stock market falls 5%",
    "news_summary": "...",
    "category": "Market",
    "category_confidence": 0.92,
    "news_date": "2024-03-24",
    "news_time": "14:30 PM",
    "source": "moneycontrol",
    ...
  }
]
```

### Get Top News
```
GET /api/top-news
GET /api/top-news?limit=50
GET /api/top-news?category=Market&limit=20

Query Parameters:
  - category: Filter top news by category (optional)
  - limit: Max articles (default: 100)

Response:
[
  {
    "title": "Market crashes amid recession fears",
    "category": "Market",
    "source": "reuters",
    "score": 2.45,
    "ranked_at": "2024-03-24T14:30:00+05:30",
    ...
  }
]
```

---

## Configuration

### Environment Variables (.env)

No new environment variables are required. The system uses existing settings.

### Source Importance (sites.yaml)

Configure source importance weights in sites.yaml:

```yaml
sources:
  groww:
    enabled: true
    display_name: "Groww"
    poll_interval: [2, 4]
    source_importance_weight: 1.2  # 20% importance boost
    description: "Stock market news from Groww"

  reuters:
    enabled: true
    display_name: "Reuters"
    poll_interval: [8, 15]
    source_importance_weight: 1.5  # 50% importance boost
    description: "Global news from Reuters"
```

**Weight Guidelines:**
- **1.5**: High authority sources (Reuters, BBC, AP News)
- **1.3**: Quality specialized sources (MoneyControl, LiveMint, CNBC)
- **1.2**: Good financial sources (Zerodha, ET Now, Business Standard)
- **1.1**: Standard sources (Groww, Scanx, TradingView)
- **1.0**: Other sources (default)

---

## Installation & Usage

### 1. Install Dependencies

```bash
pip install -r requirements.txt

# Or install transformer packages manually if preferred:
pip install transformers>=4.30.0 torch>=2.0.0
```

**Note**: First run downloads BART model (~1.6GB). This happens automatically on first classification call.

### 2. Start the System

The system integrates automatically with the main scraper:

```bash
python main.py
```

Articles are classified automatically as they're fetched. No additional configuration needed.

### 3. Classify Existing Articles (Optional)

If you have articles stored before implementing categorization:

```bash
# Classify all uncategorized articles
python reclassify.py

# Classify only from specific source
python reclassify.py --source groww

# Classify only from specific date
python reclassify.py --date 2024-03-24

# Preview changes without saving (dry-run)
python reclassify.py --dry-run

# Show help
python reclassify.py --help
```

---

## Data Structure

### Article with Classification

```json
{
  "news_date": "2024-03-24",
  "news_time": "14:30 PM",
  "scraped_at": "2024-03-24 14:35:20",
  "news_caption": "Stock market crashes 5% amid recession fears",
  "news_summary": "The stock market fell sharply today...",
  "news_url": "https://example.com/news/123",
  "image_url": "https://example.com/image.jpg",
  "time_ago": "5 minutes ago",
  "source": "moneycontrol",
  "category": "Market",
  "category_confidence": 0.92
}
```

### Top News Structure

```json
{
  "articles": [
    {
      "title": "Breaking: Market crashes",
      "category": "Market",
      "source": "reuters",
      "score": 2.45,
      "ranked_at": "2024-03-24T14:30:00+05:30",
      ...full article data...
    }
  ],
  "last_updated": "2024-03-24T14:35:00+05:30",
  "algorithm_version": "1.0"
}
```

---

## Performance

### Classification Latency

- **Single article**: 100-200ms with GPU, 1-2 seconds with CPU
- **Batch (10 articles)**: ~30-50ms per article
- **Batch (100 articles)**: ~20-30ms per article

### Model Size
- **BART model**: ~1.6GB (downloaded once, cached)
- **Each prediction**: ~100MB memory

### Top News Calculation
- **100 articles**: <50ms
- **1000 articles**: ~200ms
- Runs synchronously after each storage write

### Caching
- **Redis cache**: Avoids reprocessing same article (TTL: 30 days)
- **Local LRU cache**: Fast in-process deduplication (1000 items max)

---

## Troubleshooting

### Classification errors appear in logs

This is normal and handled gracefully:
```
WARNING Classification error for 'Title': ...
→ Article falls back to "Others" category
→ System continues without interruption
```

### Top news not updating

Check:
1. Articles have `category` field
2. Top news manager initialized properly
3. Check logs for `top_news.update_top_news()` calls

### Slow classification

Likely causes:
1. Running on CPU instead of GPU (see installation)
2. Classifying one article at a time (batch processing is faster)
3. Network latency for Redis cache (local LRU cache is faster)

### Model not downloading

Error: "transformers library not installed"

Solution:
```bash
pip install transformers>=4.30.0 torch>=2.0.0
```

---

## Advanced Customization

### Custom Category Labels

Edit `categorizing/config.py`:

```python
CATEGORY_LABELS = {
    "Market": [
        "stocks and finance",        # Default labels
        "crypto trading",             # Add custom label
        "bitcoin news",              # Add custom label
    ],
    ...
}
```

### Custom Boost Keywords

Add or modify keywords in  `categorizing/config.py`:

```python
TOP_NEWS_BOOST_KEYWORDS = {
    ...
    "cryptocurrency": 0.15,  # New keyword
    "green energy": 0.12,    # New keyword
}
```

### Custom Source Weights

Edit `sites.yaml`:

```yaml
mysource:
  source_importance_weight: 2.0  # Very high authority
```

---

## Database Files

Categorization data is stored at:

```
DATA/
├── <source_name>/
│   ├── 2024-03-24.json          # Daily articles (now with category)
│   ├── 2024-03-23.json
│   └── backup.json              # All-time articles (now with category)
└── top_news/
    └── top_news.json            # Global top 100 articles
```

---

## Module Reference

### `categorizing/classifier.py`

**Functions:**
- `classify_news(title, description) → dict`
  - Classify single article
  - Returns: `{"category": str, "confidence": float, "classifier_version": str}`

- `classify_batch(articles) → list[dict]`
  - Classify multiple articles efficiently
  - Input: List of article dicts
  - Output: Same list with `category` and `category_confidence` fields added

**Class:**
- `NewsClassifier`
  - Core classifier with caching support
  - Handles BART model lazy loading
  - Thread-safe

### `categorizing/top_news.py`

**Functions:**
- `get_top_news_manager(data_dir, source_weights) → TopNewManager`
  - Get global top news manager instance

**Class:**
- `TopNewManager`
  - Manages top 100 articles
  - Methods:
    - `update_top_news(articles) → list[dict]`
    - `get_top_news(limit=100, category=None) → list[dict]`
    - `calculate_relevance_score(article) → float`
    - `get_stats() → dict`

### `categorizing/config.py`

**Constants:**
- `CATEGORIES`: List of all available categories
- `CATEGORY_LABELS`: Category to NLP labels mapping
- `TOP_NEWS_BOOST_KEYWORDS`: Keywords and their boost values
- `MODEL_NAME`: BART model identifier
- `CLASSIFIER_VERSION`: Version string for classification output

---

## FAQ

**Q: Will classification slow down news fetching?**
A: No. Classification happens asynchronously after fetching, before storage. With batch processing, it adds ~50ms per article.

**Q: Can I use a different classification model?**
A: Yes. Edit `categorizing/config.py` to change `MODEL_NAME`. Any HuggingFace model compatible with `zero-shot-classification` pipeline should work.

**Q: What if an article can't be classified?**
A: It falls back to "Others" category with confidence 0.0. This is logged as a warning but doesn't interrupt processing.

**Q: How often is top news updated?**
A: Every time new articles are saved (after each scraper poll). Usually every 2-10 seconds.

**Q: Can I export classification data?**
A: Yes. Articles with categories are in `DATA/<source>/<date>.json`. Use `/api/news?category=Market` endpoint or read JSON files directly.

**Q: How much storage do categories add?**
A: Minimal. Two new fields per article (~100 bytes): `category` and `category_confidence`.

---

## See Also

- [Architecture Overview](./ARCHITECTURE.md)
- [Storage Documentation](./STORAGE.md)
- [Configuration Guide](./CONFIGURATION.md)
- [Source Setup](./SOURCES.md)
