# Hybrid News Categorization System

## Status

This feature is implemented and active in the ingestion pipeline.

This document describes everything added in this implementation cycle, from the initial low-latency hybrid classifier to dashboard category visibility and URL-aware accuracy upgrades.

---

## 1) What Was Added

The system now supports real-time, deterministic, multi-label categorization for each scraped article.

Implemented capabilities:
- Strict category set: business, markets, politics, india, world, others
- Multi-label output (1 to 3 labels)
- Deterministic scoring and merge logic
- Hybrid classification strategy:
  - source priors
  - keyword and phrase scoring
  - lightweight entity-style boosts
  - URL section and token scoring
  - optional fallback model (fastText or logistic regression)
- Strong off-domain detection to send irrelevant/non-core news to others
- Ingestion-time enrichment of article payload with categories and primary category
- Dashboard category tabs, counts, card chips, and filtering (news + top news)

---

## 2) Implementation Timeline (From Start of This Chat)

### Phase A: Core Categorizer Engine
- Added categorizing/fast_categorizer.py.
- Implemented modular functions:
  - classify_by_source
  - classify_by_keywords
  - classify_by_ner
  - fallback_model
  - final_category_merge
- Added deterministic category merge and in-memory thread-safe LRU caching.

### Phase B: Pipeline Integration
- Integrated categorization into main.py worker flow.
- New and one-shot fetched items are categorized before save and ranking updates.
- Added category fields on article objects:
  - categories: list of labels
  - category: primary label

### Phase C: Dashboard Integration
- Added category tabs in dashboard/index.html.
- Added styles for tabs and chips in dashboard/style.css.
- Added filter state, counts, normalization, and chip rendering in dashboard/app.js.
- Category filtering now works for both regular news feed and top news feed.

### Phase D: Accuracy Hardening
- Reduced source-overbias for broad publishers.
- Added stronger off-domain signals for sports, entertainment, education, relationship, and similar non-core items.
- Fixed merge behavior so others can remain primary when it truly wins.
- Added URL-aware categorization using source + path sections + path tokens.

### Phase E: URL-Aware Precision Upgrade
- Added section-level scoring maps and source-specific URL rules.
- Added URL token-level scoring.
- Added URL-based others override for clear off-domain pages.
- Validated example like Business Standard health page to classify as others.

---

## 3) Architecture

Primary file:
- categorizing/fast_categorizer.py

Integration points:
- main.py (worker and one-shot ingestion paths)
- categorizing/__init__.py (exports)
- dashboard/index.html
- dashboard/style.css
- dashboard/app.js

### Data Flow

Scraper fetches article
-> Categorizer computes category scores
-> Merge selects 1 to 3 labels deterministically
-> Article enriched with categories and category
-> Stored in DATA JSON
-> Top news pipeline updates
-> Dashboard reads and filters by category

---

## 4) Category Contract

Allowed labels only:
- business
- markets
- politics
- india
- world
- others

Hard constraints:
- Maximum 3 labels per item
- Deterministic ordering by score then priority
- others acts as fallback and off-domain sink

---

## 5) Scoring Pipeline

### 5.1 Source Prior Scoring
Source-specific priors initialize base category weights.

Use case:
- Financial sources tend to lift markets/business.
- Global wire sources may lift world.

Note:
Source priors are now intentionally moderated so content evidence can override weak source assumptions.

### 5.2 Keyword and Phrase Scoring
Title + summary + content are normalized and tokenized.

Scoring components:
- Token set intersection by category
- Phrase match boosts by category
- Slight uplift for others in off-domain terms

### 5.3 Lightweight NER-Style Scoring
Entity-like hints (location/org patterns) lift:
- india for India-specific cues
- world for global cues
- business/markets for organization/market tokens

### 5.4 URL Section Scoring (New)
The URL path is parsed into section signals.

Examples:
- /markets/... boosts markets/business
- /sports/... strongly boosts others
- /health/... strongly boosts others
- /exams-results/... strongly boosts others

The URL model combines:
- generic section map
- source-specific section map
- URL token map

### 5.5 Domain Gating and Others Routing
A domain signal stage checks:
- off_domain_hits
- finance_hits
- politics_hits
- hard_others state

Effects:
- weak finance/politics evidence suppresses business/markets priors
- strong off-domain signal can directly route to others
- URL others score can force others in clear cases

### 5.6 Optional Fallback Model
When confidence is low, optional model scoring is used if artifacts are available:
- fastText model
- logistic regression + TF-IDF artifacts

No model file means no fallback score (graceful no-op).

### 5.7 Final Deterministic Merge
Weighted merge combines:
- source scores
- keyword scores
- URL scores
- ner scores
- fallback scores

Post-rules:
- choose labels above threshold relative to top score
- cap to max_labels (default 3)
- preserve others when it is true winner

---

## 6) Ingestion Integration Details

During ingestion, each item is categorized and stored with:
- categories: list[str]
- category: str (primary label)

This is applied consistently in:
- continuous worker loop
- one-shot run path

Backward compatibility:
- Existing consumers using category continue to work.
- New consumers can use categories for multi-label use cases.

---

## 7) Dashboard Behavior

Added UI behavior:
- Category tabs with active state
- Per-category counts
- Category chips shown on cards
- Filter behavior for:
  - latest news feed
  - top news feed

Categories shown in tabs:
- latest
- business
- markets
- politics
- india
- world
- others

If old items are missing categories, UI fallback behavior still works.

---

## 8) Performance Characteristics

Designed for low-latency ingestion:
- set-based keyword operations
- cached tokenization
- thread-safe LRU for classification outputs
- optional fallback invoked only under low confidence
- deterministic pure-Python path when no model files exist

---

## 9) Tuning Guide

Adjust behavior in categorizing/fast_categorizer.py:

1. Source influence
- Edit SOURCE_CATEGORY_MAP weights.

2. Domain vocabulary
- Edit TOKEN_KEYWORDS and PHRASE_KEYWORDS.

3. Others routing aggressiveness
- Tune OFF_DOMAIN_* sets and domain gate thresholds.

4. URL intelligence
- Tune URL_SECTION_SCORE_MAP, SOURCE_URL_SECTION_MAP, URL_TOKEN_SCORE_MAP.

5. Merge strictness
- Tune fallback_threshold and selection thresholds in final_category_merge.

---

## 10) Validation Notes

Representative checks after accuracy upgrades:
- Off-domain/sports/education/celebrity style headlines moved to others more reliably.
- URL-based edge case fixed:
  - business-standard.com/health/... now maps to others as expected.

Audit scripts were run against DATA/backup.json to verify trend improvement and edge-case handling.

---

## 11) Output Schema

Stored article shape now includes:

{
  "news_caption": "...",
  "news_summary": "...",
  "news_url": "...",
  "source": "...",
  "categories": ["markets", "business"],
  "category": "markets"
}

Rules:
- category is always categories[0]
- categories always contains 1 to 3 labels
- labels always come from strict category contract

---

## 12) Known Tradeoffs

- Heuristic system remains rule-driven, so rare language/domain shifts may still need dictionary/map updates.
- Some borderline finance-lifestyle content can still require tuning.
- URL mapping quality depends on section naming consistency by source.

---

## 13) Operational Note

For historical data captured before these upgrades, run a backfill recategorization pass if you want old archives and dashboard views to reflect new logic immediately.

### Re-tag Existing Data

Use the helper script from project root:

- Dry run (no writes): python retag_news.py --dry-run
- Re-tag DATA fully: python retag_news.py --roots DATA
- Re-tag multiple roots: python retag_news.py --roots DATA DATA_older
- Re-tag only selected sources: python retag_news.py --source tradingview --source timesofindia
- Include DAYWISE mirror files too: python retag_news.py --include-daywise
- For dashboard all-source consistency with source filter: python retag_news.py --source tradingview --include-daywise

Default behavior:
- Processes normal source JSON files, backup.json, and top_news files.
- Skips DAYWISE mirrors unless --include-daywise is passed.

Important:
- The dashboard all-source feed reads DAYWISE mirror data.
- If you re-tag with --source and do not pass --include-daywise, source files can be up to date while all-source dashboard cards still look stale.

