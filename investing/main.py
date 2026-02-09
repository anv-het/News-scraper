"""
Investing.com Scraper - Main Entry Point
Supports one-time execution and cron-style scheduling.
"""

import sys
import time
import random
import argparse
from datetime import datetime, timedelta
from pathlib import Path

from config import get_config, reload_config
from logger import setup_logger, get_logger
from fetch_equities import EquitiesFetcher
from fetch_news import NewsScraper


class ScraperOrchestrator:
    """Orchestrates equities and news scraping with scheduling support."""
    
    def __init__(self):
        self.config = get_config()
        self.logger = get_logger("orchestrator")
        self._last_run_file = self.config.paths.base_dir / ".last_run"
    
    def _get_last_run_time(self) -> datetime:
        """Get the last successful run time."""
        try:
            if self._last_run_file.exists():
                with open(self._last_run_file, 'r') as f:
                    timestamp = f.read().strip()
                    return datetime.fromisoformat(timestamp)
        except Exception:
            pass
        return datetime.min
    
    def _set_last_run_time(self):
        """Record the current time as last run."""
        try:
            with open(self._last_run_file, 'w') as f:
                f.write(datetime.now().isoformat())
        except Exception as e:
            self.logger.warning(f"Failed to save last run time: {e}")
    
    def _should_run_today(self) -> bool:
        """Check if we should run based on days gap."""
        if self.config.cron.days_gap <= 0:
            return True
        
        last_run = self._get_last_run_time()
        days_since = (datetime.now() - last_run).days
        
        return days_since >= self.config.cron.days_gap
    
    def _is_within_time_window(self) -> bool:
        """Check if current time is within allowed window."""
        current_hour = datetime.now().hour
        return self.config.cron.start_hour <= current_hour < self.config.cron.end_hour
    
    def _wait_for_time_window(self):
        """Wait until the time window opens."""
        while not self._is_within_time_window():
            current = datetime.now()
            target_hour = self.config.cron.start_hour
            
            if current.hour >= self.config.cron.end_hour:
                # Wait until tomorrow
                target = current.replace(
                    hour=target_hour, 
                    minute=0, 
                    second=0, 
                    microsecond=0
                ) + timedelta(days=1)
            else:
                # Wait until start hour today
                target = current.replace(
                    hour=target_hour, 
                    minute=0, 
                    second=0, 
                    microsecond=0
                )
            
            wait_seconds = (target - current).total_seconds()
            self.logger.info(f"Outside time window. Waiting until {target.strftime('%H:%M')} ({wait_seconds/60:.0f} minutes)")
            
            # Sleep in chunks to allow interruption
            chunk = min(wait_seconds, 300)  # 5 minute chunks
            time.sleep(chunk)
    
    def _random_start_delay(self):
        """Add random delay before starting."""
        if self.config.cron.random_start_delay_max > 0:
            delay_minutes = random.randint(0, self.config.cron.random_start_delay_max)
            if delay_minutes > 0:
                self.logger.info(f"Random start delay: {delay_minutes} minutes")
                time.sleep(delay_minutes * 60)
    
    def run_equities(self) -> bool:
        """Run equities fetcher."""
        self.logger.info("Running Equities Fetcher...")
        fetcher = EquitiesFetcher()
        return fetcher.run()
    
    def run_news(self) -> bool:
        """Run news scraper."""
        self.logger.info("Running News Scraper...")
        scraper = NewsScraper()
        return scraper.run()
    
    def run_once(self, fetch_equities: bool = True, fetch_news: bool = True) -> bool:
        """
        Run a single scraping cycle.
        
        Args:
            fetch_equities: Whether to fetch equities list
            fetch_news: Whether to scrape news
        
        Returns:
            True if successful
        """
        self.logger.info("=" * 60)
        self.logger.info(f"Starting scraping run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 60)
        
        success = True
        
        if fetch_equities:
            if not self.run_equities():
                self.logger.error("Equities fetch failed")
                success = False
        
        if fetch_news:
            if not self.run_news():
                self.logger.error("News scrape failed")
                success = False
        
        if success:
            self._set_last_run_time()
        
        self.logger.info("=" * 60)
        self.logger.info(f"Scraping run completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 60)
        
        return success
    
    def run_scheduled(self):
        """
        Run in scheduled/cron mode.
        Waits for time window and respects days gap.
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting in SCHEDULED mode")
        self.logger.info(f"Time window: {self.config.cron.start_hour}:00 - {self.config.cron.end_hour}:00")
        self.logger.info(f"Days gap: {self.config.cron.days_gap}")
        self.logger.info("=" * 60)
        
        while True:
            try:
                # Check if we should run today
                if not self._should_run_today():
                    last_run = self._get_last_run_time()
                    next_run = last_run + timedelta(days=self.config.cron.days_gap)
                    self.logger.info(f"Not due to run yet. Last run: {last_run.date()}, Next run: {next_run.date()}")
                    time.sleep(3600)  # Check again in 1 hour
                    continue
                
                # Wait for time window
                if not self._is_within_time_window():
                    self._wait_for_time_window()
                
                # Random delay before starting
                self._random_start_delay()
                
                # Run the scraping
                self.run_once(fetch_equities=True, fetch_news=True)
                
                # After successful run, wait for next day
                self.logger.info("Run complete. Waiting for next scheduled time...")
                time.sleep(3600)  # Check again in 1 hour
                
            except KeyboardInterrupt:
                self.logger.info("Interrupted by user. Exiting...")
                break
            except Exception as e:
                self.logger.error(f"Error in scheduled run: {e}")
                time.sleep(300)  # Wait 5 minutes before retrying


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Investing.com India Equities & News Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Run once (equities + news)
  python main.py --news-only        # Scrape news only
  python main.py --equities-only    # Fetch equities only
  python main.py --scheduled        # Run in scheduled/cron mode
  python main.py --test             # Test mode (limited equities)
        """
    )
    
    parser.add_argument(
        '--equities-only',
        action='store_true',
        help='Only fetch equities list, skip news scraping'
    )
    
    parser.add_argument(
        '--news-only',
        action='store_true',
        help='Only scrape news, skip equities fetch'
    )
    
    parser.add_argument(
        '--scheduled',
        action='store_true',
        help='Run in scheduled/cron mode (respects time window and days gap)'
    )
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run in test mode (limited equities)'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    try:
        args = parse_args()
        
        # Reload config to pick up any changes
        config = reload_config()
        
        # Override config with CLI args
        if args.test:
            config.scraper.test_mode = True
        
        if args.scheduled:
            config.cron.enabled = True
        
        # Set up logging
        log_level = "DEBUG" if args.debug else config.logging.level
        setup_logger(
            log_level=log_level,
            log_to_file=config.logging.log_to_file,
            log_dir=str(config.paths.log_dir)
        )
        
        logger = get_logger("main")
        logger.info(f"Starting Investing.com Scraper")
        logger.info(f"Base directory: {config.paths.base_dir}")
        logger.info(f"Output directory: {config.paths.output_dir}")
        
        # Create orchestrator
        orchestrator = ScraperOrchestrator()
        
        # Determine what to run
        if config.cron.enabled or args.scheduled:
            orchestrator.run_scheduled()
        else:
            fetch_equities = not args.news_only
            fetch_news = not args.equities_only
            
            success = orchestrator.run_once(
                fetch_equities=fetch_equities,
                fetch_news=fetch_news
            )
            return 0 if success else 1
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\nProcess stopped by user. Exiting...")
        return 0
    except Exception as e:
        print(f"\n\nAn unexpected error occurred: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
