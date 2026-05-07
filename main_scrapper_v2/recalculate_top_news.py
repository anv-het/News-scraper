"""
Recalculate top news scores after changing source importance weights.

Usage:
    python recalculate_top_news.py              # Recalculate from all articles in DATA/
    python recalculate_top_news.py --from-all   # Same as above
    python recalculate_top_news.py --show-stats # Show before/after comparison

This is useful when you change source_importance_weight values in sites.yaml —
it ensures all existing articles get rescored based on new weights.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.time_utils import IST, now_ist
from categorizing.config import TOP_NEWS_BOOST_KEYWORDS, DEFAULT_SOURCE_WEIGHTS
from categorizing.top_news import TopNewManager

logger = logging.getLogger("recalculate_top_news")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def load_source_weights() -> dict:
    """Load source importance weights from sites.yaml."""
    sites_path = PROJECT_ROOT / "sites.yaml"
    if not sites_path.exists():
        logger.warning("sites.yaml not found, using defaults")
        return DEFAULT_SOURCE_WEIGHTS

    try:
        with open(sites_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f).get("sources", {})

        weights = {}
        for source_name, source_cfg in config.items():
            weight = source_cfg.get("source_importance_weight", 1.0)
            weights[source_name.lower()] = weight

        logger.info(f"Loaded {len(weights)} source weights from sites.yaml")
        return weights
    except Exception as e:
        logger.error(f"Failed to load sites.yaml: {e}")
        return DEFAULT_SOURCE_WEIGHTS


def collect_all_articles(data_dir: str) -> list[dict]:
    """Collect all articles from DATA/ folder by source."""
    articles = []

    # Convert to absolute path if relative
    data_path = Path(data_dir).resolve()

    if not data_path.exists():
        logger.error(f"Data directory not found: {data_path}")
        logger.error(f"Current working directory: {Path.cwd()}")
        return articles

    logger.info(f"Scanning: {data_path}")

    # Scan each source folder
    source_count = 0
    for source_folder in data_path.iterdir():
        if not source_folder.is_dir() or source_folder.name in ["top_news", ".cache", "DAYWISE"]:
            continue

        source_name = source_folder.name
        source_count += 1
        logger.debug(f"Scanning source: {source_name}")

        # Scan for JSON files in source folder (flat structure: source/YYYY-MM-DD.json)
        file_count = 0
        for file_path in source_folder.glob("*.json"):
            if file_path.name == "backup.json":
                continue
            file_count += 1
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, list):
                    articles.extend(data)
                    logger.debug(f"  {file_path.name}: {len(data)} articles")
                elif isinstance(data, dict) and "articles" in data:
                    articles.extend(data["articles"])
                    logger.debug(f"  {file_path.name}: {len(data['articles'])} articles")
            except Exception as e:
                logger.warning(f"Could not read {file_path}: {e}")

        if file_count == 0:
            logger.debug(f"  No JSON files found in {source_name}")

    logger.info(f"Scanned {source_count} sources")

    logger.info(f"Collected {len(articles)} articles from {data_dir}")
    return articles


def get_old_scores(top_news_file: str) -> dict:
    """Load old scores from existing top_news.json for comparison."""
    old_scores = {}

    if os.path.exists(top_news_file):
        try:
            with open(top_news_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for article in data.get("articles", []):
                article_id = article.get("id", "")
                old_score = article.get("score", 0)
                if article_id:
                    old_scores[article_id] = old_score
        except Exception as e:
            logger.warning(f"Could not load old scores: {e}")

    return old_scores


def show_comparison(top_news_mgr: TopNewManager, old_scores: dict, old_top_news: list):
    """Show before/after comparison of top news."""
    new_top_news = top_news_mgr.get_top_news(limit=10)

    logger.info("\n" + "="*80)
    logger.info("TOP 10 COMPARISON (Before vs After)")
    logger.info("="*80)
    logger.info(f"{'Rank':<5} {'Source':<18} {'Old Score':<12} {'New Score':<12} {'Change':<10}")
    logger.info("-"*80)

    for i, new_article in enumerate(new_top_news[:10], 1):
        article_id = new_article.get("id", "")
        source = new_article.get("source", "Unknown")
        new_score = new_article.get("score", 0)
        old_score = old_scores.get(article_id, 0)
        change = new_score - old_score
        change_pct = (change / old_score * 100) if old_score > 0 else 0

        logger.info(
            f"{i:<5} {source:<18} {old_score:<12.2f} {new_score:<12.2f} "
            f"{change:+.2f} ({change_pct:+.1f}%)"
        )

    logger.info("-"*80)
    logger.info(f"Total articles in top news: {len(top_news_mgr.get_top_news())} : {len(new_top_news)}")
    logger.info("="*80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Recalculate top news scores after changing source weights"
    )
    parser.add_argument(
        "--from-all", action="store_true",
        help="Recalculate from all articles in DATA/ (default behavior)"
    )
    parser.add_argument(
        "--show-stats", action="store_true",
        help="Show before/after comparison of top 10 articles"
    )
    parser.add_argument(
        "--data-dir", default="DATA",
        help="Data directory (default: DATA)"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Update logging level if debug is enabled
    if args.debug:
        logger.setLevel(logging.DEBUG)

    # Resolve data_dir: if relative, make it relative to script location
    data_dir = args.data_dir
    if not Path(data_dir).is_absolute():
        data_dir = str(PROJECT_ROOT / data_dir)

    logger.debug(f"Script location: {PROJECT_ROOT}")
    logger.debug(f"Data directory: {data_dir}")

    # Load new source weights
    logger.info("Loading source importance weights from sites.yaml...")
    source_weights = load_source_weights()

    logger.info(f"Loaded {len(source_weights)} source weights:")
    for source, weight in sorted(source_weights.items()):
        logger.info(f"  {source:<18} : {weight}")

    logger.info(f"\nDEBUG: source_weights dict = {source_weights}")

    # Create top news manager with new weights
    logger.info(f"\nInitializing TopNewManager with new weights...")
    logger.debug(f"Passing source_weights to TopNewManager: {source_weights}")
    top_news_mgr = TopNewManager(
        data_dir=data_dir,
        source_weights=source_weights,
        semantic_config={"enabled": False},
    )

    # Get old scores if we need to show comparison
    top_news_file = os.path.join(data_dir, "top_news", "top_news.json")
    old_scores = {}
    old_top_news = []

    if args.show_stats:
        old_scores = get_old_scores(top_news_file)
        with open(top_news_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            old_top_news = data.get("articles", [])

    # Collect all articles
    logger.info("\nCollecting articles from DATA folder...")
    all_articles = collect_all_articles(data_dir)

    if not all_articles:
        logger.error("No articles found to recalculate!")
        return 1

    # Recalculate top news
    logger.info(f"\nRecalculating scores for {len(all_articles)} articles...")

    # Diagnostic: sample a few articles to debug scoring
    if all_articles:
        logger.info("\n=== DIAGNOSTIC: Sampling 5 articles ===")
        logger.info(f"TOP WEIGHTS AVAILABLE: {top_news_mgr.source_weights}\n")

        for i, article in enumerate(all_articles[:5]):
            source_raw = article.get("source", "unknown")
            source = source_raw.lower()
            title = article.get("news_caption", "")[:60]

            time_score = top_news_mgr._calculate_time_score(article)
            keyword_boost = top_news_mgr._calculate_keyword_boost(article)
            source_weight = top_news_mgr._get_source_weight(article)
            score = top_news_mgr.calculate_relevance_score(article)

            logger.info(f"\n[{i+1}] {title}")
            logger.info(f"    Article source field: '{source_raw}' lowercase: '{source}'")
            logger.info(f"    Source weight lookup: '{source}' in weights? {source in top_news_mgr.source_weights}")
            logger.info(f"    Result weight: {source_weight}")
            logger.info(f"    Time score: {time_score:.4f} | Keyword boost: {keyword_boost:.4f} | Final score: {score:.4f}")

            # Check if keywords are matching
            text = (article.get("news_caption", "") + " " + article.get("news_summary", "")).lower()
            from categorizing.config import TOP_NEWS_BOOST_KEYWORDS
            matched_keywords = [kw for kw in TOP_NEWS_BOOST_KEYWORDS.keys() if kw in text]
            if matched_keywords:
                logger.info(f"    Matched keywords: {matched_keywords[:3]}")
            else:
                logger.info(f"    No keywords matched")
        logger.info("\n===================================\n")

    top_news, newly_crowned = top_news_mgr.update_top_news(all_articles)

    logger.info(f"Top news updated with {len(top_news)} articles")
    logger.info(f"Added {len(newly_crowned)} new articles to historical top news")

    # Show stats if requested
    if args.show_stats:
        show_comparison(top_news_mgr, old_scores, old_top_news)

    # Show source breakdown
    stats = top_news_mgr.get_stats()
    logger.info("\nFinal Top News Stats:")
    logger.info(f"  Total articles: {stats['total_articles']}")
    logger.info(f"  Score range: {stats['oldest_score']:.2f} – {stats['newest_score']:.2f}")
    logger.info(f"  By category: {stats['by_category']}")
    logger.info(f"  Last updated: {stats['last_updated']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
