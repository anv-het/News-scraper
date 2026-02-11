"""
Groww Stock Data Scraper

Fetches all stock data from Groww's all_stocks API using curl_cffi
with Chrome TLS impersonation — bypasses checksum requirement entirely.

Usage:
    python fetch_stocks.py
"""

import json
import csv
import time
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

from curl_cffi import requests

from config import get_config
from logger import setup_logger, get_logger


API_URL = "https://groww.in/v1/api/stocks_data/v1/all_stocks"


class GrowwStockFetcher:
    """Fetches all stock data from Groww API using curl_cffi."""

    def __init__(self):
        self.config = get_config()
        self.logger = get_logger("stock_fetcher")
        self.session = requests.Session(impersonate="chrome120")

    def _headers(self) -> Dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "x-app-id": "growwWeb",
            "x-device-type": "desktop",
            "x-platform": "web",
            "x-device-id": str(uuid.uuid4()),
            "x-request-id": str(uuid.uuid4()),
            "origin": "https://groww.in",
            "referer": "https://groww.in/stocks",
        }

    def _body(self, page: int) -> Dict[str, Any]:
        return {
            "listFilters": {"INDUSTRY": [], "INDEX": []},
            "objFilters": {
                "CLOSE_PRICE": {
                    "min": self.config.filters.min_price,
                    "max": self.config.filters.max_price,
                },
                "MARKET_CAP": {
                    "min": self.config.filters.min_market_cap,
                    "max": self.config.filters.max_market_cap,
                },
            },
            "page": str(page),
            "size": str(self.config.scraper.page_size),
            "sortBy": self.config.scraper.sort_by,
            "sortType": self.config.scraper.sort_type,
        }

    def fetch_page(self, page: int, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """Fetch a single page of stock data."""
        for attempt in range(max_retries):
            try:
                resp = self.session.post(
                    API_URL,
                    headers=self._headers(),
                    json=self._body(page),
                    timeout=self.config.delays.request_timeout,
                )

                if resp.status_code == 429:
                    wait = 30 * (attempt + 1)
                    self.logger.warning(f"Rate limited (429). Waiting {wait}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code != 200:
                    self.logger.warning(f"Page {page}: HTTP {resp.status_code}")
                    if attempt < max_retries - 1:
                        time.sleep(5 * (attempt + 1))
                        continue
                    return None

                return resp.json()

            except Exception as e:
                self.logger.error(f"Page {page} attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))

        return None

    def fetch_all(self) -> List[Dict[str, Any]]:
        """Paginate through all stocks."""
        self.logger.info("=" * 60)
        self.logger.info("Groww Stock Fetcher — Starting")
        self.logger.info("=" * 60)

        all_stocks = []
        page = 0
        total = None

        while True:
            page_label = f"page {page}" + (f" / ~{total}" if total else "")
            self.logger.info(f"Fetching {page_label}...")

            data = self.fetch_page(page)
            if data is None:
                self.logger.error(f"Failed to fetch page {page}. Stopping.")
                break

            records = data.get("records", [])
            if not records:
                self.logger.info("No more records. Pagination complete.")
                break

            all_stocks.extend(records)

            # Calculate total pages on first response
            total_records = data.get("totalRecords", 0)
            if total is None and total_records:
                total = (total_records + self.config.scraper.page_size - 1) // self.config.scraper.page_size
                self.logger.info(f"Total stocks: {total_records} across ~{total} pages")

            self.logger.info(f"  Got {len(records)} stocks (collected: {len(all_stocks)})")

            # Check if done
            if total_records and len(all_stocks) >= total_records:
                self.logger.info("All stocks collected!")
                break

            page += 1

            # Random delay
            delay = random.uniform(self.config.delays.min_delay, self.config.delays.max_delay)
            self.logger.debug(f"Waiting {delay:.1f}s...")
            time.sleep(delay)

        self.logger.info(f"Total fetched: {len(all_stocks)} stocks")
        return all_stocks

    # ------------------------------------------------------------------
    # Save methods
    # ------------------------------------------------------------------

    def save_json(self, stocks: List[Dict], path: Optional[Path] = None) -> Optional[Path]:
        """Save to JSON (latest + timestamped copy)."""
        out_dir = Path(self.config.output.directory)
        out_dir.mkdir(parents=True, exist_ok=True)

        if path is None:
            path = out_dir / "groww_stocks.json"

        ts_path = out_dir / f"groww_stocks_{datetime.now():%Y%m%d_%H%M%S}.json"

        payload = {
            "fetched_at": datetime.now().isoformat(),
            "total_stocks": len(stocks),
            "stocks": stocks,
        }

        try:
            for p in (path, ts_path):
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved JSON: {path}")
            self.logger.info(f"Timestamped: {ts_path}")
            return path
        except Exception as e:
            self.logger.error(f"JSON save failed: {e}")
            return None

    def save_csv(self, stocks: List[Dict], path: Optional[Path] = None) -> Optional[Path]:
        """Save to CSV with flattened nested dicts."""
        if not stocks:
            return None

        out_dir = Path(self.config.output.directory)
        out_dir.mkdir(parents=True, exist_ok=True)

        if path is None:
            path = out_dir / "groww_stocks.csv"

        try:
            flat = []
            for stock in stocks:
                row = {}
                for k, v in stock.items():
                    if isinstance(v, dict):
                        for sk, sv in v.items():
                            row[f"{k}_{sk}"] = sv
                    else:
                        row[k] = v
                flat.append(row)

            keys = sorted({k for row in flat for k in row})

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(flat)

            self.logger.info(f"Saved CSV: {path}")
            return path
        except Exception as e:
            self.logger.error(f"CSV save failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self) -> bool:
        """Fetch all stocks and save."""
        stocks = self.fetch_all()
        if not stocks:
            self.logger.error("No stocks fetched")
            return False

        fmt = self.config.output.format.lower()
        if fmt in ("json", "both"):
            self.save_json(stocks)
        if fmt in ("csv", "both"):
            self.save_csv(stocks)

        # Summary
        self.logger.info("=" * 60)
        self.logger.info(f"DONE — {len(stocks)} stocks fetched and saved")
        self.logger.info("=" * 60)

        if stocks:
            self.logger.info("Sample stocks:")
            for s in stocks[:5]:
                name = s.get("companyName", s.get("companyShortName", "N/A"))
                price = s.get("closePrice", "N/A")
                self.logger.info(f"  • {name} — ₹{price}")

        return True


def main():
    try:
        config = get_config()
        setup_logger(log_level=config.logging.level, log_to_file=config.logging.log_to_file)

        fetcher = GrowwStockFetcher()
        return 0 if fetcher.run() else 1
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 0
    except Exception as e:
        print(f"\nFatal error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
