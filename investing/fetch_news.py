"""
Investing.com News Scraper
Fetches news articles for each equity from Investing.com.
Uses curl_cffi and BeautifulSoup for scraping.
"""

import csv
import json
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup

from config import get_config
from logger import setup_logger, get_logger

# HTTP client setup
try:
    from curl_cffi import requests
    HTTP_CLIENT = "curl_cffi"
except ImportError:
    import requests
    HTTP_CLIENT = "requests"


class NewsScraper:
    """Scrapes news articles for equities from Investing.com."""
    
    BASE_URL = "https://in.investing.com"
    
    def __init__(self):
        self.config = get_config()
        self.logger = get_logger("news_scraper")
        self._equities_scraped = 0
    
    def load_equities(self) -> List[Dict[str, Any]]:
        """
        Load equities from JSON file.
        
        Returns:
            List of equity dicts
        """
        json_path = self.config.paths.equities_json
        
        # Also check parent output directory if not found
        if not json_path.exists():
            alt_path = self.config.paths.base_dir.parent / "output" / "equities_india_latest.json"
            if alt_path.exists():
                json_path = alt_path
        
        if not json_path.exists():
            self.logger.error(f"Equities JSON not found: {json_path}")
            return []
        
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            equities = data.get('data', [])
            self.logger.info(f"Loaded {len(equities)} equities from: {json_path}")
            return equities
        except Exception as e:
            self.logger.error(f"Failed to load equities: {e}")
            return []
    
    def fetch_news_page(self, equity_url: str, page: int = 1) -> Optional[str]:
        """
        Fetch a single news page for an equity.
        
        Args:
            equity_url: URL path from JSON, e.g., "/equities/aditya-birla"
            page: Page number (1, 2, 3, ...)
        
        Returns:
            HTML content or None if error
        """
        news_url = f"{self.BASE_URL}{equity_url}-news/{page}"
        
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if HTTP_CLIENT == "curl_cffi":
                    response = requests.get(
                        news_url,
                        headers=headers,
                        impersonate="chrome",
                        timeout=self.config.delays.request_timeout
                    )
                else:
                    response = requests.get(
                        news_url,
                        headers=headers,
                        timeout=self.config.delays.request_timeout
                    )
                
                if response.status_code == 200:
                    return response.text
                elif response.status_code == 404:
                    self.logger.warning(f"Page {page} not found (404)")
                    return None
                else:
                    self.logger.warning(f"Page {page} returned status {response.status_code}. Retrying ({attempt+1}/{max_retries})...")
                    # Exponential backoff for status errors
                    sleep_time = 5 * (attempt + 1)
                    if response.status_code in (429, 503):
                        sleep_time *= 2  # Double wait for rate limits
                    time.sleep(sleep_time)
            
            except Exception as e:
                self.logger.warning(f"Attempt {attempt+1} failed for page {page}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
                else:
                    self.logger.error(f"Failed to fetch page {page} after {max_retries} attempts: {e}")
                    return None
        
        return None
    
    def parse_news_articles(self, html: str) -> List[Dict[str, Any]]:
        """
        Parse news articles from HTML.
        
        Returns:
            List of article dicts with: title, link, source, source_url, date, description
        """
        soup = BeautifulSoup(html, 'html.parser')
        news_list = soup.find('ul', {'data-test': 'news-list'})
        
        if not news_list:
            return []
        
        articles = []
        for article in news_list.find_all('article', {'data-test': 'article-item'}):
            try:
                item = {}
                
                # Title and Link - use data-test="article-title-link"
                title_link = article.find('a', {'data-test': 'article-title-link'})
                if title_link:
                    item['title'] = title_link.get_text(strip=True)
                    item['link'] = title_link.get('href', '')
                else:
                    continue  # Skip if no title
                
                # Description - use data-test="article-description"
                desc = article.find('p', {'data-test': 'article-description'})
                if desc:
                    item['description'] = desc.get_text(strip=True)
                else:
                    # Fallback to any <p> tag
                    p_tag = article.find('p')
                    if p_tag:
                        item['description'] = p_tag.get_text(strip=True)
                
                # Source - use data-test="article-provider-link"
                source_link = article.find('a', {'data-test': 'article-provider-link'})
                if source_link:
                    item['source'] = source_link.get_text(strip=True)
                    source_href = source_link.get('href', '')
                    # Build full URL if relative
                    if source_href.startswith('/'):
                        item['source_url'] = f"{self.BASE_URL}{source_href}"
                    elif source_href:
                        item['source_url'] = source_href
                else:
                    # Fallback - look for source span pattern
                    li_elements = article.find_all('li')
                    for li in li_elements:
                        by_span = li.find('span', string=lambda t: t and 'By' in t if t else False)
                        if by_span:
                            # Find the next sibling or child <a>
                            link = li.find('a')
                            if link:
                                item['source'] = link.get_text(strip=True)
                                href = link.get('href', '')
                                if href.startswith('/'):
                                    item['source_url'] = f"{self.BASE_URL}{href}"
                                elif href:
                                    item['source_url'] = href
                            break
                
                # Date - use data-test="article-publish-date" or <time> element
                time_elem = article.find('time', {'data-test': 'article-publish-date'})
                if not time_elem:
                    time_elem = article.find('time')
                
                if time_elem:
                    item['date'] = time_elem.get('datetime', '')
                    item['date_display'] = time_elem.get_text(strip=True)
                
                articles.append(item)
                
            except Exception as e:
                self.logger.warning(f"Error parsing article: {e}")
                continue
        
        return articles
    
    def _random_delay(self, min_sec: float, max_sec: float):
        """Sleep for a random duration."""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)
        return delay
    
    def _long_break(self):
        """Take a long break after batch_size equities."""
        break_minutes = random.uniform(
            self.config.delays.break_min_minutes,
            self.config.delays.break_max_minutes
        )
        self.logger.info(f"Taking a {break_minutes:.1f} minute break after {self.config.delays.batch_size} equities...")
        time.sleep(break_minutes * 60)
    
    def scrape_equity_news(self, equity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Scrape all news pages for a single equity.
        
        Args:
            equity: Equity dict with 'Url', 'Name', 'Symbol'
        
        Returns:
            List of all articles
        """
        equity_url = equity.get('Url', '')
        equity_name = equity.get('Name', 'Unknown')
        equity_symbol = equity.get('Symbol', 'N/A')
        
        if not equity_url:
            return []
        
        self.logger.info(f"[{equity_symbol}] Scraping news for: {equity_name}")
        
        all_articles = []
        page = 1
        max_pages = self.config.scraper.max_pages_per_equity
        
        while page <= max_pages:
            html = self.fetch_news_page(equity_url, page)
            
            if not html:
                break
            
            articles = self.parse_news_articles(html)
            
            if not articles:
                self.logger.debug(f"  No more articles at page {page}")
                break
            
            all_articles.extend(articles)
            self.logger.debug(f"  Page {page}: {len(articles)} articles (total: {len(all_articles)})")
            
            page += 1
            
            # Random delay between pages
            if page <= max_pages:
                self._random_delay(
                    self.config.delays.page_delay_min,
                    self.config.delays.page_delay_max
                )
        
        self.logger.info(f"  Found {len(all_articles)} total articles across {page-1} pages")
        return all_articles
    
    def save_news(self, equity: Dict[str, Any], articles: List[Dict[str, Any]]) -> Optional[Path]:
        """
        Save news articles to JSON file.
        
        Args:
            equity: Equity dict
            articles: List of article dicts
        
        Returns:
            Path to saved file or None if error
        """
        output_dir = self.config.paths.json_output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        
        equity_id = equity.get('Id', 'unknown')
        equity_symbol = equity.get('Symbol', 'unknown')
        equity_name = equity.get('Name', '')
        
        # Sanitize filename
        safe_symbol = "".join(c if c.isalnum() else "_" for c in equity_symbol)
        filename = f"{equity_id}_{safe_symbol}.json"
        filepath = output_dir / filename
        
        data = {
            'equity_id': equity_id,
            'equity_name': equity_name,
            'equity_symbol': equity_symbol,
            'equity_url': equity.get('Url', ''),
            'fetched_at': datetime.now().isoformat(),
            'total_articles': len(articles),
            'articles': articles
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.logger.debug(f"  Saved JSON to: {filepath}")
            
            # Also save CSV if enabled
            if self.config.paths.enable_csv_output:
                self.save_news_csv(equity, articles)
            
            return filepath
        except Exception as e:
            self.logger.error(f"Failed to save news JSON: {e}")
            return None
    
    def save_news_csv(self, equity: Dict[str, Any], articles: List[Dict[str, Any]]) -> Optional[Path]:
        """
        Save news articles to CSV file.
        
        Args:
            equity: Equity dict
            articles: List of article dicts
        
        Returns:
            Path to saved file or None if error
        """
        output_dir = self.config.paths.csv_output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        
        equity_id = equity.get('Id', 'unknown')
        equity_symbol = equity.get('Symbol', 'unknown')
        equity_name = equity.get('Name', '')
        equity_url = equity.get('Url', '')
        
        # Sanitize filename
        safe_symbol = "".join(c if c.isalnum() else "_" for c in equity_symbol)
        filename = f"{equity_id}_{safe_symbol}.csv"
        filepath = output_dir / filename
        
        # CSV columns
        fieldnames = [
            'equity_id', 'equity_name', 'equity_symbol', 'equity_url',
            'title', 'link', 'description', 'source', 'source_url', 'date', 'date_display',
            'fetched_at'
        ]
        
        fetched_at = datetime.now().isoformat()
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                
                for article in articles:
                    row = {
                        'equity_id': equity_id,
                        'equity_name': equity_name,
                        'equity_symbol': equity_symbol,
                        'equity_url': equity_url,
                        'title': article.get('title', ''),
                        'link': article.get('link', ''),
                        'description': article.get('description', ''),
                        'source': article.get('source', ''),
                        'source_url': article.get('source_url', ''),
                        'date': article.get('date', ''),
                        'date_display': article.get('date_display', ''),
                        'fetched_at': fetched_at
                    }
                    writer.writerow(row)
                
            self.logger.debug(f"  Saved CSV to: {filepath}")
            return filepath
        except Exception as e:
            self.logger.error(f"Failed to save news CSV: {e}")
            return None
    
    def save_to_mongodb(self, equity: Dict[str, Any], articles: List[Dict[str, Any]]) -> bool:
        """
        Save news articles to MongoDB.
        
        Args:
            equity: Equity dict
            articles: List of article dicts
        
        Returns:
            True if successful, False otherwise
        """
        if not self.config.mongodb.enabled:
            return True
        
        try:
            from pymongo import MongoClient
            
            client = MongoClient(self.config.mongodb.url)
            db = client[self.config.mongodb.database]
            collection = db[self.config.mongodb.news_collection]
            
            equity_id = equity.get('Id', 'unknown')
            equity_symbol = equity.get('Symbol', 'unknown')
            
            # Prepare document
            doc = {
                'equity_id': equity_id,
                'equity_name': equity.get('Name', ''),
                'equity_symbol': equity_symbol,
                'equity_url': equity.get('Url', ''),
                'fetched_at': datetime.utcnow(),
                'updated_at': datetime.utcnow(),
                'total_articles': len(articles),
                'articles': articles
            }
            
            # Upsert by equity_id
            result = collection.update_one(
                {'equity_id': equity_id},
                {'$set': doc, '$setOnInsert': {'created_at': datetime.utcnow()}},
                upsert=True
            )
            
            if result.upserted_id:
                self.logger.debug(f"  MongoDB: inserted news for {equity_symbol}")
            elif result.modified_count > 0:
                self.logger.debug(f"  MongoDB: updated news for {equity_symbol}")
            
            client.close()
            return True
            
        except ImportError:
            self.logger.error("pymongo not installed. Run: pip install pymongo")
            return False
        except Exception as e:
            self.logger.error(f"MongoDB save failed for {equity.get('Symbol', 'unknown')}: {e}")
            return False
    
    def should_skip_equity(self, equity: Dict[str, Any]) -> bool:
        """Check if equity should be skipped (already scraped)."""
        if not self.config.scraper.skip_existing:
            return False
        
        equity_id = equity.get('Id', 'unknown')
        equity_symbol = equity.get('Symbol', 'unknown')
        safe_symbol = "".join(c if c.isalnum() else "_" for c in equity_symbol)
        filename = f"{equity_id}_{safe_symbol}.json"
        filepath = self.config.paths.json_output_dir / filename
        
        return filepath.exists()
    
    def run(self) -> bool:
        """
        Run the news scraper for all equities.
        
        Returns:
            True if successful, False otherwise
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting News Scraper")
        self.logger.info(f"HTTP client: {HTTP_CLIENT}")
        self.logger.info("=" * 60)
        
        # Load equities
        equities = self.load_equities()
        if not equities:
            self.logger.error("No equities loaded. Run fetch_equities first.")
            return False
        
        # Apply test mode limit
        if self.config.scraper.test_mode:
            equities = equities[:self.config.scraper.test_limit]
            self.logger.info(f"[TEST MODE] Processing only {len(equities)} equities")
        
        # Process each equity
        total_articles = 0
        skipped = 0
        self._equities_scraped = 0
        
        for i, equity in enumerate(equities, 1):
            # Check if should skip
            if self.should_skip_equity(equity):
                self.logger.debug(f"[{i}/{len(equities)}] Skipping (already exists): {equity.get('Symbol', 'N/A')}")
                skipped += 1
                continue
            
            self.logger.info(f"[{i}/{len(equities)}] Processing...")
            
            articles = self.scrape_equity_news(equity)
            
            if articles:
                self.save_news(equity, articles)
                # Save to MongoDB if enabled
                if self.config.mongodb.enabled:
                    self.save_to_mongodb(equity, articles)
                total_articles += len(articles)
            
            self._equities_scraped += 1
            
            # Long break after batch
            if (self._equities_scraped > 0 and 
                self._equities_scraped % self.config.delays.batch_size == 0 and 
                i < len(equities)):
                self._long_break()
            
            # Random delay between equities
            elif i < len(equities):
                delay = self._random_delay(
                    self.config.delays.equity_delay_min,
                    self.config.delays.equity_delay_max
                )
                self.logger.debug(f"  Waiting {delay:.1f}s before next equity...")
        
        self.logger.info("=" * 60)
        self.logger.info(f"Scraping complete!")
        self.logger.info(f"  Processed: {self._equities_scraped} equities")
        self.logger.info(f"  Skipped: {skipped} (already existed)")
        self.logger.info(f"  Total articles: {total_articles}")
        self.logger.info("=" * 60)
        
        return True


def main():
    """Main entry point for standalone execution."""
    try:
        config = get_config()
        setup_logger(
            log_level=config.logging.level,
            log_to_file=config.logging.log_to_file,
            log_dir=str(config.paths.log_dir)
        )
        
        scraper = NewsScraper()
        success = scraper.run()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n\nProcess stopped by user. Exiting...")
        return 0


if __name__ == "__main__":
    exit(main())
