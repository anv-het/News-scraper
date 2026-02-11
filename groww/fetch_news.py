"""
Groww News Fetcher

Fetches news for every company in groww_stocks.json using the Groww news API.
Paginates per company until empty results.

Saves:
  - Per-company JSON: output/news/CompanyName-ISIN.json
  - Per-company CSV:  output/news/CompanyName-ISIN.csv
  - MongoDB (optional): upserts news documents

Usage:
    python fetch_news.py
"""

import json
import csv
import re
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

from curl_cffi import requests as curl_requests

from config import get_config
from logger import setup_logger, get_logger


NEWS_API = "https://groww.in/v1/api/groww-news/v2/stocks/news/{contract_id}?page={page}&size={size}"


def sanitize_filename(name: str) -> str:
    """Remove/replace characters that are invalid in filenames on Windows/Linux."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.replace(' ', '_')
    name = re.sub(r'_+', '_', name)
    return name.strip('_.')


class GrowwNewsFetcher:
    """Fetches news for all companies from Groww."""

    def __init__(self):
        self.config = get_config()
        self.logger = get_logger("news_fetcher")
        self.session = curl_requests.Session(impersonate="chrome120")
        self.stocks: List[Dict] = []

    def load_stocks(self, stocks_path: Optional[Path] = None) -> List[Dict]:
        """Load the stocks list from groww_stocks.json."""
        if stocks_path is None:
            stocks_path = Path(self.config.output.directory) / "groww_stocks.json"

        try:
            with open(stocks_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.stocks = data.get("stocks", [])
            self.logger.info(f"Loaded {len(self.stocks)} stocks from {stocks_path}")
            return self.stocks
        except FileNotFoundError:
            self.logger.error(f"Stocks file not found: {stocks_path}")
            self.logger.error("Run fetch_stocks.py first to generate the stocks list.")
            return []
        except Exception as e:
            self.logger.error(f"Failed to load stocks: {e}")
            return []

    def _headers(self) -> Dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "x-app-id": "growwWeb",
            "x-device-type": "desktop",
            "x-platform": "web",
            "origin": "https://groww.in",
            "referer": "https://groww.in/stocks",
        }

    def fetch_news_for_stock(self, contract_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all news for a single stock by paginating until empty.

        Args:
            contract_id: Groww contract ID (e.g., GSTK500325)

        Returns:
            List of all news articles for this stock
        """
        all_news = []
        page = 0
        size = self.config.news.page_size

        while True:
            url = NEWS_API.format(contract_id=contract_id, page=page, size=size)

            try:
                resp = self.session.get(
                    url,
                    headers=self._headers(),
                    timeout=self.config.delays.request_timeout,
                )

                if resp.status_code == 429:
                    self.logger.warning(f"Rate limited on {contract_id} page {page}. Waiting 30s...")
                    time.sleep(30)
                    continue

                if resp.status_code != 200:
                    self.logger.warning(f"{contract_id} page {page}: HTTP {resp.status_code}")
                    break

                data = resp.json()
                results = data.get("results", [])

                if not results:
                    break

                all_news.extend(results)
                page += 1

                # Small delay between pages of the same stock
                time.sleep(random.uniform(0.5, 1.5))

            except Exception as e:
                self.logger.error(f"{contract_id} page {page} error: {e}")
                break

        return all_news

    def save_stock_news_json(self, news: List[Dict], company_name: str, isin: str) -> Optional[Path]:
        """Save news for a single company to JSON."""
        out_dir = Path(self.config.news.json_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{sanitize_filename(company_name)}-{isin}.json"
        path = out_dir / filename

        try:
            payload = {
                "company_name": company_name,
                "isin": isin,
                "fetched_at": datetime.now().isoformat(),
                "total_articles": len(news),
                "articles": news,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            return path
        except Exception as e:
            self.logger.error(f"Failed to save JSON for {company_name}: {e}")
            return None

    def save_stock_news_csv(self, news: List[Dict], company_name: str, isin: str) -> Optional[Path]:
        """Save news for a single company to CSV."""
        if not news:
            return None

        out_dir = Path(self.config.news.csv_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{sanitize_filename(company_name)}-{isin}.csv"
        path = out_dir / filename

        try:
            keys = sorted({k for article in news for k in article})
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(news)
            return path
        except Exception as e:
            self.logger.error(f"Failed to save CSV for {company_name}: {e}")
            return None

    def save_to_mongodb(self, news: List[Dict], company_name: str, isin: str, contract_id: str) -> bool:
        """Upsert news articles into MongoDB."""
        if not self.config.mongodb.enabled or not news:
            return True

        try:
            from pymongo import MongoClient
        except ImportError:
            self.logger.error("pymongo not installed. Run: pip install pymongo")
            return False

        try:
            client = MongoClient(self.config.mongodb.url)
            db = client[self.config.mongodb.database]
            coll = db[self.config.mongodb.collection]

            inserted = updated = 0
            for article in news:
                article_id = article.get("id")
                if not article_id:
                    continue

                doc = {
                    **article,
                    "company_name": company_name,
                    "isin": isin,
                    "growwContractId": contract_id,
                    "updated_at": datetime.utcnow(),
                }
                result = coll.update_one(
                    {"id": article_id},
                    {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
                    upsert=True,
                )
                if result.upserted_id:
                    inserted += 1
                elif result.modified_count:
                    updated += 1

            self.logger.debug(f"  MongoDB [{company_name}]: {inserted} new, {updated} updated")
            client.close()
            return True
        except Exception as e:
            self.logger.error(f"MongoDB failed for {company_name}: {e}")
            return False

    def run(self) -> bool:
        """Fetch news for all stocks and save."""
        self.logger.info("=" * 60)
        self.logger.info("Groww News Fetcher — Starting")
        self.logger.info("=" * 60)

        stocks = self.load_stocks()
        if not stocks:
            return False

        fmt = self.config.output.format.lower()
        total = len(stocks)
        success_count = 0
        total_articles = 0

        for idx, stock in enumerate(stocks, 1):
            contract_id = stock.get("growwContractId", "")
            company_name = stock.get("companyName", stock.get("companyShortName", "Unknown"))
            isin = stock.get("isin", "UNKNOWN")

            if not contract_id:
                self.logger.warning(f"[{idx}/{total}] Skipping {company_name} — no contract ID")
                continue

            self.logger.info(f"[{idx}/{total}] {company_name} ({contract_id})...")

            # Fetch all news pages for this stock
            news = self.fetch_news_for_stock(contract_id)

            if news:
                # Save JSON
                if fmt in ("json", "both"):
                    self.save_stock_news_json(news, company_name, isin)
                # Save CSV
                if fmt in ("csv", "both"):
                    self.save_stock_news_csv(news, company_name, isin)
                # MongoDB
                if self.config.mongodb.enabled:
                    self.save_to_mongodb(news, company_name, isin, contract_id)

                total_articles += len(news)
                success_count += 1
                self.logger.info(f"  → {len(news)} articles saved")
            else:
                self.logger.info(f"  → No news found")

            # Random delay between stocks
            delay = random.uniform(self.config.delays.min_delay, self.config.delays.max_delay)
            time.sleep(delay)

            # Take a break after N stocks
            if idx % self.config.breaks.after_stocks == 0 and idx < total:
                break_mins = random.uniform(
                    self.config.breaks.min_minutes,
                    self.config.breaks.max_minutes,
                )
                self.logger.info(
                    f"Taking a break after {idx} stocks — "
                    f"pausing for {break_mins:.1f} minutes..."
                )
                time.sleep(break_mins * 60)

        # Summary
        self.logger.info("=" * 60)
        self.logger.info(f"DONE — {total_articles} articles from {success_count}/{total} companies")
        self.logger.info("=" * 60)

        return True


def main():
    try:
        config = get_config()
        setup_logger(log_level=config.logging.level, log_to_file=config.logging.log_to_file)

        fetcher = GrowwNewsFetcher()
        return 0 if fetcher.run() else 1
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 0
    except Exception as e:
        print(f"\nFatal error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
