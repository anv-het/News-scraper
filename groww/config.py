"""
Configuration loader for Groww scraper.
Reads .env and provides typed access to all settings.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv


load_dotenv(Path(__file__).parent / ".env")


def _env(key, default=""):
    return os.getenv(key, default).strip()

def _int(key, default=0):
    try: return int(_env(key, str(default)))
    except ValueError: return default

def _float(key, default=0.0):
    try: return float(_env(key, str(default)))
    except ValueError: return default

def _bool(key, default=False):
    return _env(key, str(default)).lower() in ("true", "1", "yes")


@dataclass
class OutputConfig:
    directory: Path = field(default_factory=lambda: Path(_env("OUTPUT_DIR", "output")))
    format: str = field(default_factory=lambda: _env("OUTPUT_FORMAT", "json"))

@dataclass
class NewsConfig:
    json_dir: Path = field(default_factory=lambda: Path(_env("NEWS_JSON_DIR", "output/news/json")))
    csv_dir: Path = field(default_factory=lambda: Path(_env("NEWS_CSV_DIR", "output/news/csv")))
    page_size: int = field(default_factory=lambda: _int("NEWS_PAGE_SIZE", 50))

@dataclass
class ScraperConfig:
    page_size: int = field(default_factory=lambda: _int("PAGE_SIZE", 50))
    sort_by: str = field(default_factory=lambda: _env("SORT_BY", "NA"))
    sort_type: str = field(default_factory=lambda: _env("SORT_TYPE", "ASC"))

@dataclass
class FilterConfig:
    min_price: float = field(default_factory=lambda: _float("MIN_PRICE", 0))
    max_price: float = field(default_factory=lambda: _float("MAX_PRICE", 500000))
    min_market_cap: float = field(default_factory=lambda: _float("MIN_MARKET_CAP", 0))
    max_market_cap: float = field(default_factory=lambda: _float("MAX_MARKET_CAP", 3e15))

@dataclass
class DelayConfig:
    min_delay: float = field(default_factory=lambda: _float("MIN_DELAY", 2))
    max_delay: float = field(default_factory=lambda: _float("MAX_DELAY", 6))
    request_timeout: int = field(default_factory=lambda: _int("REQUEST_TIMEOUT", 30))

@dataclass
class BreakConfig:
    after_stocks: int = field(default_factory=lambda: _int("BREAK_AFTER_STOCKS", 100))
    min_minutes: float = field(default_factory=lambda: _float("BREAK_MIN_MINUTES", 5))
    max_minutes: float = field(default_factory=lambda: _float("BREAK_MAX_MINUTES", 15))

@dataclass
class CronConfig:
    enabled: bool = field(default_factory=lambda: _bool("CRON_ENABLED", False))
    day_gap: int = field(default_factory=lambda: _int("CRON_DAY_GAP", 1))
    start_time: str = field(default_factory=lambda: _env("CRON_START_TIME", "09:00"))
    end_time: str = field(default_factory=lambda: _env("CRON_END_TIME", "20:00"))

@dataclass
class LoggingConfig:
    level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    log_to_file: bool = field(default_factory=lambda: _bool("LOG_TO_FILE", True))

@dataclass
class MongoDBConfig:
    enabled: bool = field(default_factory=lambda: _bool("MONGODB_ENABLED", False))
    url: str = field(default_factory=lambda: _env("MONGODB_URL", "mongodb://localhost:27017"))
    database: str = field(default_factory=lambda: _env("MONGODB_DATABASE", "groww"))
    collection: str = field(default_factory=lambda: _env("MONGODB_COLLECTION", "news"))

@dataclass
class Config:
    output: OutputConfig = field(default_factory=OutputConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    delays: DelayConfig = field(default_factory=DelayConfig)
    breaks: BreakConfig = field(default_factory=BreakConfig)
    cron: CronConfig = field(default_factory=CronConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    mongodb: MongoDBConfig = field(default_factory=MongoDBConfig)


_config = None

def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
