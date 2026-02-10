"""
Investing.com Equities Fetcher
Fetches equity data from Investing.com API for India (country-id=14)
and saves it as JSON.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from config import get_config
from logger import setup_logger, get_logger

# HTTP client setup
try:
    from curl_cffi import requests
    HTTP_CLIENT = "curl_cffi"
except ImportError:
    try:
        import cloudscraper
        HTTP_CLIENT = "cloudscraper"
    except ImportError:
        import requests
        HTTP_CLIENT = "requests"


class EquitiesFetcher:
    """Fetches equity listings from Investing.com API."""
    
    API_URL = "https://api.investing.com/api/financialdata/assets/equitiesByCountry/default"
    
    def __init__(self):
        self.config = get_config()
        self.logger = get_logger("equities_fetcher")
        
    def fetch(self, country_id: int = 14, page_size: int = 8000, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        Fetch equities data from Investing.com API.
        
        Args:
            country_id: Country ID (14 = India)
            page_size: Number of results per page
            max_retries: Maximum retry attempts for failed requests
        
        Returns:
            JSON data dict or None if error
        """
        params = {
            "fields-list": "name,symbol,url",
            "country-id": country_id,
            "page": 0,
            "page-size": page_size
        }
        
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.investing.com",
            "Referer": "https://www.investing.com/",
            "domain-id": "www",
        }
        
        self.logger.info(f"Fetching equities data (country_id={country_id})...")
        self.logger.debug(f"Using HTTP client: {HTTP_CLIENT}")
        
        for attempt in range(max_retries):
            try:
                if HTTP_CLIENT == "curl_cffi":
                    response = requests.get(
                        self.API_URL,
                        params=params,
                        headers=headers,
                        timeout=self.config.delays.request_timeout,
                        impersonate="chrome"
                    )
                elif HTTP_CLIENT == "cloudscraper":
                    scraper = cloudscraper.create_scraper(
                        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
                    )
                    response = scraper.get(
                        self.API_URL,
                        params=params,
                        headers=headers,
                        timeout=self.config.delays.request_timeout
                    )
                else:
                    response = requests.get(
                        self.API_URL,
                        params=params,
                        headers=headers,
                        timeout=self.config.delays.request_timeout
                    )
                
                response.raise_for_status()
                data = response.json()
                
                count = len(data.get('data', []))
                self.logger.info(f"Successfully fetched {count} equities")
                return data
                
            except Exception as e:
                error_msg = str(e)
                is_timeout = "504" in error_msg or "timeout" in error_msg.lower() or "502" in error_msg
                
                if attempt < max_retries - 1:
                    # Exponential backoff: 15s, 30s, 45s (longer for API calls)
                    sleep_time = 15 * (attempt + 1)
                    if is_timeout:
                        sleep_time *= 2  # Double wait for timeouts
                    self.logger.warning(f"Request failed: {e}. Retrying in {sleep_time}s ({attempt + 1}/{max_retries})...")
                    time.sleep(sleep_time)
                else:
                    self.logger.error(f"Failed to fetch equities after {max_retries} attempts: {e}")
                    return None
        
        return None
    
    def save(self, data: Dict[str, Any], output_path: Optional[Path] = None) -> Optional[Path]:
        """
        Save equities data to JSON file.
        
        Args:
            data: Equities data dict
            output_path: Output file path (optional, uses config default)
        
        Returns:
            Path to saved file or None if error
        """
        if output_path is None:
            output_path = self.config.paths.equities_json
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Also save timestamped version
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        timestamped_path = output_path.parent / f"equities_india_{timestamp}.json"
        
        try:
            # Save latest version
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved equities to: {output_path}")
            
            # Save timestamped version
            with open(timestamped_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.logger.debug(f"Saved timestamped copy: {timestamped_path}")
            
            return output_path
            
        except Exception as e:
            self.logger.error(f"Failed to save equities: {e}")
            return None
    
    # def save_to_mongodb(self, data: Dict[str, Any]) -> bool:
        """
        Save equities data to MongoDB.
        
        Args:
            data: Equities data dict
        
        Returns:
            True if successful, False otherwise
        """
        if not self.config.mongodb.enabled:
            return True
        
        try:
            from pymongo import MongoClient
            
            client = MongoClient(self.config.mongodb.url)
            db = client[self.config.mongodb.database]
            collection = db[self.config.mongodb.equities_collection]
            
            # Test connection
            client.admin.command('ping')
            self.logger.info(f"Connected to MongoDB: {self.config.mongodb.database}.{self.config.mongodb.equities_collection}")
            
            equities = data.get('data', [])
            if not equities:
                self.logger.warning("No equities to save to MongoDB")
                return True
            
            # Upsert each equity by Id
            inserted = 0
            updated = 0
            for equity in equities:
                equity_id = equity.get('Id')
                if not equity_id:
                    continue
                
                doc = {
                    **equity,
                    'updated_at': datetime.utcnow()
                }
                
                result = collection.update_one(
                    {'Id': equity_id},
                    {'$set': doc, '$setOnInsert': {'created_at': datetime.utcnow()}},
                    upsert=True
                )
                
                if result.upserted_id:
                    inserted += 1
                elif result.modified_count > 0:
                    updated += 1
            
            self.logger.info(f"MongoDB: {inserted} inserted, {updated} updated")
            client.close()
            return True
            
        except ImportError:
            self.logger.error("pymongo not installed. Run: pip install pymongo")
            return False
        except Exception as e:
            self.logger.error(f"MongoDB save failed: {e}")
            return False
    
    def run(self) -> bool:
        """
        Run the equities fetcher.
        
        Returns:
            True if successful, False otherwise
        """
        self.logger.info("=" * 50)
        self.logger.info("Starting Equities Fetcher")
        self.logger.info("=" * 50)
        
        data = self.fetch()
        if not data:
            self.logger.error("Failed to fetch equities data")
            return False
        
        # Save to JSON file
        saved_path = self.save(data)
        if not saved_path:
            self.logger.error("Failed to save equities data")
            return False
        
        # Save to MongoDB if enabled
        if self.config.mongodb.enabled:
            self.save_to_mongodb(data)
        
        # Print summary
        count = len(data.get('data', []))
        self.logger.info(f"Total equities: {count}")
        
        if count > 0:
            self.logger.info("Sample equities:")
            for equity in data['data'][:5]:
                self.logger.info(f"  - {equity.get('Name', 'N/A')} ({equity.get('Symbol', 'N/A')})")
        
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
        
        fetcher = EquitiesFetcher()
        success = fetcher.run()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n\nProcess stopped by user. Exiting...")
        return 0


if __name__ == "__main__":
    exit(main())
