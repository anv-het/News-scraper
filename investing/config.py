"""
Configuration management for the Investing.com scraper.
Loads settings from environment variables and .env file.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Load .env file
try:
    from dotenv import load_dotenv
    # Look for .env in the script directory
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass


@dataclass
class PathConfig:
    """File and directory path configuration."""
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.resolve())
    output_dir: Path = field(default=None)
    json_output_dir: Path = field(default=None)
    csv_output_dir: Path = field(default=None)
    news_output_dir: Path = field(default=None)  # Deprecated, use json_output_dir
    equities_json: Path = field(default=None)
    log_dir: Path = field(default=None)
    enable_csv_output: bool = field(default=True)
    
    def __post_init__(self):
        self.output_dir = Path(os.getenv("OUTPUT_DIR", self.base_dir / "output"))
        self.json_output_dir = Path(os.getenv("JSON_OUTPUT_DIR", self.output_dir / "json"))
        self.csv_output_dir = Path(os.getenv("CSV_OUTPUT_DIR", self.output_dir / "csv"))
        # Keep news_output_dir for backward compatibility, maps to json_output_dir
        self.news_output_dir = Path(os.getenv("NEWS_OUTPUT_DIR", self.json_output_dir))
        self.equities_json = Path(os.getenv("EQUITIES_JSON", self.output_dir / "equities_india_latest.json"))
        self.log_dir = Path(os.getenv("LOG_DIR", self.base_dir / "logs"))
        self.enable_csv_output = os.getenv("ENABLE_CSV_OUTPUT", str(self.enable_csv_output)).lower() in ("true", "1", "yes")
        
        # Create directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.json_output_dir.mkdir(parents=True, exist_ok=True)
        if self.enable_csv_output:
            self.csv_output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class DelayConfig:
    """Delay and throttling configuration."""
    # Delay between fetching pages (seconds)
    page_delay_min: float = field(default=2.0)
    page_delay_max: float = field(default=5.0)
    
    # Delay between different equities (seconds)
    equity_delay_min: float = field(default=3.0)
    equity_delay_max: float = field(default=8.0)
    
    # Long break settings
    batch_size: int = field(default=50)  # Take a break after this many equities
    break_min_minutes: float = field(default=5.0)
    break_max_minutes: float = field(default=15.0)
    
    # Request timeout (seconds)
    request_timeout: int = field(default=60)
    
    def __post_init__(self):
        self.page_delay_min = float(os.getenv("PAGE_DELAY_MIN", self.page_delay_min))
        self.page_delay_max = float(os.getenv("PAGE_DELAY_MAX", self.page_delay_max))
        self.equity_delay_min = float(os.getenv("EQUITY_DELAY_MIN", self.equity_delay_min))
        self.equity_delay_max = float(os.getenv("EQUITY_DELAY_MAX", self.equity_delay_max))
        self.batch_size = int(os.getenv("BATCH_SIZE", self.batch_size))
        self.break_min_minutes = float(os.getenv("BREAK_MIN_MINUTES", self.break_min_minutes))
        self.break_max_minutes = float(os.getenv("BREAK_MAX_MINUTES", self.break_max_minutes))
        self.request_timeout = int(os.getenv("REQUEST_TIMEOUT", self.request_timeout))


@dataclass
class ScraperConfig:
    """Scraper behavior configuration."""
    # Maximum pages to scrape per equity
    max_pages_per_equity: int = field(default=100)
    
    # Test mode - limit number of equities
    test_mode: bool = field(default=False)
    test_limit: int = field(default=5)
    
    # Skip already scraped equities (check if JSON exists)
    skip_existing: bool = field(default=True)
    
    def __post_init__(self):
        self.max_pages_per_equity = int(os.getenv("MAX_PAGES_PER_EQUITY", self.max_pages_per_equity))
        self.test_mode = os.getenv("TEST_MODE", str(self.test_mode)).lower() in ("true", "1", "yes")
        self.test_limit = int(os.getenv("TEST_LIMIT", self.test_limit))
        self.skip_existing = os.getenv("SKIP_EXISTING", str(self.skip_existing)).lower() in ("true", "1", "yes")


@dataclass
class CronConfig:
    """Cron job and scheduling configuration."""
    # Enable cron-style scheduling
    enabled: bool = field(default=False)
    
    # Time range during which scraping can happen (24-hour format)
    start_hour: int = field(default=9)
    end_hour: int = field(default=22)
    
    # Days gap between full scrapes (0 = run every day)
    days_gap: int = field(default=1)
    
    # Random start delay within the time window (minutes)
    random_start_delay_max: int = field(default=30)
    
    def __post_init__(self):
        self.enabled = os.getenv("CRON_ENABLED", str(self.enabled)).lower() in ("true", "1", "yes")
        self.start_hour = int(os.getenv("CRON_START_HOUR", self.start_hour))
        self.end_hour = int(os.getenv("CRON_END_HOUR", self.end_hour))
        self.days_gap = int(os.getenv("CRON_DAYS_GAP", self.days_gap))
        self.random_start_delay_max = int(os.getenv("CRON_RANDOM_START_DELAY_MAX", self.random_start_delay_max))


@dataclass
class LogConfig:
    """Logging configuration."""
    level: str = field(default="INFO")
    log_to_file: bool = field(default=True)
    
    def __post_init__(self):
        self.level = os.getenv("LOG_LEVEL", self.level).upper()
        self.log_to_file = os.getenv("LOG_TO_FILE", str(self.log_to_file)).lower() in ("true", "1", "yes")


@dataclass
class MongoDBConfig:
    """MongoDB configuration."""
    enabled: bool = field(default=False)
    url: str = field(default="mongodb://localhost:27017")
    database: str = field(default="investing_scraper")
    equities_collection: str = field(default="equities")
    news_collection: str = field(default="news")
    
    def __post_init__(self):
        self.enabled = os.getenv("MONGODB_ENABLED", str(self.enabled)).lower() in ("true", "1", "yes")
        self.url = os.getenv("MONGODB_URL", self.url)
        self.database = os.getenv("MONGODB_DATABASE", self.database)
        # self.equities_collection = os.getenv("MONGODB_EQUITIES_COLLECTION", self.equities_collection)
        self.news_collection = os.getenv("MONGODB_NEWS_COLLECTION", self.news_collection)


@dataclass
class Config:
    """Main configuration class that aggregates all config sections."""
    paths: PathConfig = field(default_factory=PathConfig)
    delays: DelayConfig = field(default_factory=DelayConfig)
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    cron: CronConfig = field(default_factory=CronConfig)
    logging: LogConfig = field(default_factory=LogConfig)
    mongodb: MongoDBConfig = field(default_factory=MongoDBConfig)


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Reload configuration from environment."""
    global _config
    _config = Config()
    return _config
