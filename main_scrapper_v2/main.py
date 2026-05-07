"""
╔══════════════════════════════════════════════════════════════════════╗
║                    NEWS SCRAPPER - MAIN ORCHESTRATOR                ║
║  Runs all enabled site scrapers concurrently with health            ║
║  monitoring, blocked-site detection, and optional dashboard.        ║
║  Designed to run 24/7 for long-term operation.                      ║
╚══════════════════════════════════════════════════════════════════════╝

Usage:
    python main.py                          # Continuous polling + dashboard
    python main.py --no-dash                # Continuous, no dashboard
    python main.py --source groww           # Run only one source (continuous)
    python main.py --once                   # Run all sources once, then exit
    python main.py --once --source groww    # Run one source once, then exit
    python main.py --cron 60                # Run all once, sleep 60s, repeat
    python main.py --cron 60 --source groww # Cron for one source
    python main.py --test                   # Test all sources (fetch once, report)
    python main.py --test --source groww    # Test one source
"""

import argparse
import importlib
import os
import random
import signal
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from logger import setup_logger, SourceLogger
from health.api_server import start_dashboard
from storage.json_storage import JsonStorage
from storage.mongo_storage import MongoStorage
from storage.redis_cache import RedisCache
from utils.proxy import ProxyManager
from sites_scrapers.base import BaseScraper
from categorizing.fast_categorizer import get_news_categorizer
from categorizing.top_news import get_top_news_manager

# ─── Configuration ───────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load all configuration from .env and sites.yaml."""
    cfg = {
        "project_name": os.getenv("PROJECT_NAME", "NewsScrapper"),
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "data_dir": os.getenv("DATA_DIR", "DATA"),
        "log_dir": os.getenv("LOG_DIR", "logs"),
        "dashboard_enabled": os.getenv("DASHBOARD_ENABLED", "true").lower() == "true",
        "dashboard_host": os.getenv("DASHBOARD_HOST", "0.0.0.0"),
        "dashboard_port": int(os.getenv("DASHBOARD_PORT", "8080")),
        "redis_enabled": os.getenv("REDIS_ENABLED", "false").lower() == "true",
        "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "redis_prefix": os.getenv("REDIS_PREFIX", "news_scrapper"),
        "redis_seen_ttl_days": int(os.getenv("REDIS_SEEN_TTL_DAYS", "90")),
        "mongo_enabled": os.getenv("MONGO_ENABLED", "false").lower() == "true",
        "mongo_url": os.getenv("MONGO_URL", "mongodb://localhost:27017"),
        "mongo_database": os.getenv("MONGO_DATABASE", "news_scrapper"),
        "mongo_collection": os.getenv("MONGO_COLLECTION", "news"),
        "mongo_top_news_enabled": os.getenv("MONGO_TOP_NEWS_ENABLED", "false").lower() == "true",
        "mongo_top_news_collection": os.getenv("MONGO_TOP_NEWS_COLLECTION", "top_news_history"),
        "proxy_enabled": os.getenv("PROXY_ENABLED", "false").lower() == "true",
        "proxy_file": os.getenv("PROXY_FILE", "proxies.txt"),
        "proxy_bandwidth_limit_mb": int(os.getenv("PROXY_BANDWIDTH_LIMIT_MB", "1024")),
        "proxy_rotation": os.getenv("PROXY_ROTATION", "round_robin"),
        "default_timeout": int(os.getenv("DEFAULT_TIMEOUT", "20")),
        "default_poll_min": int(os.getenv("DEFAULT_POLL_MIN", "5")),
        "default_poll_max": int(os.getenv("DEFAULT_POLL_MAX", "10")),
        "max_consecutive_errors": int(os.getenv("MAX_CONSECUTIVE_ERRORS", "20")),
        "blocked_threshold_minutes": int(os.getenv("BLOCKED_THRESHOLD_MINUTES", "120")),
        "blocked_delay_min": int(os.getenv("BLOCKED_DELAY_MIN", "5")),
        "blocked_delay_max": int(os.getenv("BLOCKED_DELAY_MAX", "15")),
        "blocked_escalation_factor": float(os.getenv("BLOCKED_ESCALATION_FACTOR", "2")),
        "blocked_max_delay_min": int(os.getenv("BLOCKED_MAX_DELAY_MIN", "120")),
        "backup_write_interval": int(os.getenv("BACKUP_WRITE_INTERVAL", "60")),
        "quiet_hours_start": os.getenv("QUIET_HOURS_START", "").strip(),
        "quiet_hours_end": os.getenv("QUIET_HOURS_END", "").strip(),
        "user_agent": os.getenv(
            "USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36",
        ),
        "semantic_enabled": os.getenv("SEMANTIC_ENABLED", "true").lower() == "true",
        "semantic_cache_size": int(os.getenv("SEMANTIC_CACHE_SIZE", "20000")),
        "semantic_model": os.getenv("SEMANTIC_MODEL", "ProsusAI/finbert"),
        "semantic_fallback_model": os.getenv("SEMANTIC_FALLBACK_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
        "semantic_candidate_limit": int(os.getenv("SEMANTIC_CANDIDATE_LIMIT", "2500")),
        "semantic_text_chars": int(os.getenv("SEMANTIC_TEXT_CHARS", "420")),
        "ner_text_chars": int(os.getenv("NER_TEXT_CHARS", "240")),
        "spacy_enabled": os.getenv("SPACY_ENABLED", "true").lower() == "true",
        "spacy_model": os.getenv("SPACY_MODEL", "en_core_web_sm"),
        "recency_decay_hours": int(os.getenv("RECENCY_DECAY_HOURS", "18")),
        "topnews_dedup_top_n": os.getenv("TOPNEWS_DEDUP_TOP_N", "true").lower() == "true",
        "rank_weight_semantic": float(os.getenv("RANK_WEIGHT_SEMANTIC", "0.34")),
        "rank_weight_entity": float(os.getenv("RANK_WEIGHT_ENTITY", "0.20")),
        "rank_weight_event": float(os.getenv("RANK_WEIGHT_EVENT", "0.23")),
        "rank_weight_recency": float(os.getenv("RANK_WEIGHT_RECENCY", "0.15")),
        "rank_weight_source": float(os.getenv("RANK_WEIGHT_SOURCE", "0.08")),
        "generate_top_news_json": os.getenv("GENERATE_TOP_NEWS_JSON", "true").lower() == "true",
    }

    # Load sites.yaml
    sites_path = PROJECT_ROOT / "sites.yaml"
    if sites_path.exists():
        with open(sites_path, "r", encoding="utf-8") as f:
            cfg["sites"] = yaml.safe_load(f).get("sources", {})
    else:
        cfg["sites"] = {}

    return cfg


# ─── Quiet Hours ─────────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))


def _parse_hhmm(s: str):
    """Parse 'HH:MM' string to (hour, minute) tuple, or None if empty/invalid."""
    if not s:
        return None
    try:
        parts = s.split(":")
        return (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


def is_quiet_hours(config: dict) -> bool:
    """Return True if current IST time falls within the quiet-hours window."""
    start = _parse_hhmm(config.get("quiet_hours_start", ""))
    end = _parse_hhmm(config.get("quiet_hours_end", ""))
    if start is None or end is None:
        return False

    now = datetime.now(IST)
    now_minutes = now.hour * 60 + now.minute
    start_minutes = start[0] * 60 + start[1]
    end_minutes = end[0] * 60 + end[1]

    if start_minutes <= end_minutes:
        # Same-day range, e.g. 08:00 – 18:00
        return start_minutes <= now_minutes < end_minutes
    else:
        # Overnight range, e.g. 23:30 – 06:00
        return now_minutes >= start_minutes or now_minutes < end_minutes


# ─── Scraper Discovery ──────────────────────────────────────────────────────

def discover_scrapers(
    sites_config: dict,
    global_config: dict,
    proxy_manager: ProxyManager | None,
    redis_cache: RedisCache | None,
) -> list[BaseScraper]:
    """Dynamically import and instantiate enabled scrapers from sites_scrapers/."""
    scrapers = []

    for name, site_cfg in sites_config.items():
        if not site_cfg.get("enabled", True):
            continue

        # Merge global + site config
        merged = {**global_config, **site_cfg}
        merged["timeout"] = global_config["default_timeout"]

        try:
            module = importlib.import_module(f"sites_scrapers.{name}")
        except ImportError as e:
            print(f"[WARN] Cannot import sites_scrapers.{name}: {e}")
            continue

        # Find the BaseScraper subclass in the module
        scraper_class = None
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseScraper)
                and obj is not BaseScraper
                and getattr(obj, "name", "") == name
            ):
                scraper_class = obj
                break

        if not scraper_class:
            print(f"[WARN] No BaseScraper subclass with name='{name}' in sites_scrapers/{name}.py")
            continue

        use_proxy = site_cfg.get("use_proxy", False) and global_config.get("proxy_enabled", False)
        merged["use_proxy"] = use_proxy

        scraper = scraper_class(
            config=merged,
            proxy_manager=proxy_manager if use_proxy else None,
            redis_cache=redis_cache,
        )
        scrapers.append(scraper)

    return scrapers


# ─── Scraper Worker Thread ───────────────────────────────────────────────────

class ScraperWorker(threading.Thread):
    """Runs a single scraper in a loop with health monitoring."""

    def __init__(
        self,
        scraper: BaseScraper,
        storage: JsonStorage,
        redis_cache: RedisCache | None,
        mongo_storage: MongoStorage | None,
        config: dict,
        stop_event: threading.Event,
        top_news_mgr=None,
        categorizer=None,
    ):
        super().__init__(daemon=True, name=f"worker-{scraper.name}")
        self.scraper = scraper
        self.storage = storage
        self.redis = redis_cache
        self.mongo_storage = mongo_storage
        self.config = config
        self.stop_event = stop_event
        self.top_news_mgr = top_news_mgr
        self.categorizer = categorizer

        poll = config.get("sites", {}).get(scraper.name, {}).get(
            "poll_interval",
            [config["default_poll_min"], config["default_poll_max"]],
        )
        self.poll_min = poll[0]
        self.poll_max = poll[1]

        self.log = SourceLogger(
            __import__("logging").getLogger("scrapper"), scraper.name
        )

        # Health tracking
        self.consecutive_errors = 0
        self.consecutive_empty = 0
        self.last_success_time = time.time()
        self.last_fetch_count = 0
        self.total_fetched = 0
        self.is_blocked = False
        self.block_count = 0  # escalation counter for exponential backoff
        self.last_error = ""
        self.last_error_time = 0.0
        self._last_empty_warn_time = 0.0  # throttle empty-data warnings

    @property
    def status(self) -> str:
        if self.is_blocked:
            return "blocked"
        if self.consecutive_errors > 0:
            return "degraded"
        return "healthy"

    def run(self):
        try:
            self.scraper.setup()
        except Exception as e:
            self.log.error(f"Setup failed: {e}")
            return

        self.log.info(
            f"Fetching news for {self.scraper.name.upper()} — Poll interval: {self.poll_min}-{self.poll_max}s"
        )

        while not self.stop_event.is_set():
            # ── Quiet-hours gate ─────────────────────────────────
            if is_quiet_hours(self.config):
                if not getattr(self, "_quiet_logged", False):
                    self.log.info("Quiet hours — paused")
                    self._quiet_logged = True
                self.stop_event.wait(60)
                continue
            if getattr(self, "_quiet_logged", False):
                self.log.info("Quiet hours ended — resuming")
                self._quiet_logged = False

            # ── Blocked-site exponential backoff ─────────────────
            if self.is_blocked:
                delay_min = self._blocked_delay()
                self.log.warning(
                    f"Blocked (level {self.block_count}) — "
                    f"retrying in {delay_min:.0f}m"
                )
                self.stop_event.wait(delay_min * 60)
                if self.stop_event.is_set():
                    break
                self.is_blocked = False
                self.consecutive_errors = 0
                self.log.info("Retrying after block...")

            try:
                # Fetch news from source
                new_items = self.scraper.fetch_news()
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                self.last_error_time = time.time()
                error_msg = str(e).lower()

                # More descriptive error messages
                if "ip" in error_msg or "blocked" in error_msg or "403" in error_msg:
                    self.log.error(f"Could not fetch — Site blocked our IP")
                elif "timeout" in error_msg or "connection" in error_msg:
                    self.log.error(f"Could not fetch — Connection timeout or network error")
                else:
                    self.log.error(f"Could not fetch — {e}")

                self.consecutive_errors += 1
                self._check_blocked()
                self._backoff_sleep()
                continue

            if new_items:
                try:
                    if self.categorizer:
                        for item in new_items:
                            self.categorizer.apply_to_article(item)

                    # Save all articles immediately
                    saved = self.storage.save_news(self.scraper.name, new_items)
                    saved_items = new_items if saved > 0 else []
                    total_saved = saved

                    # Log detailed save message
                    self.log.info(f"Fetched {len(new_items)} articles — Saved {total_saved} in JSON")

                except Exception as e:
                    print(f"[{self.scraper.name}] SAVE ERROR: {type(e).__name__}: {e}", flush=True)
                    self.log.error(f"Could not save articles — {e}")
                    saved_items = []
                    total_saved = 0

                # Use total_saved count for error checking and stats
                saved = total_saved

                self.total_fetched += saved
                self.last_fetch_count = saved
                self.consecutive_errors = 0
                self.consecutive_empty = 0
                self.block_count = 0  # reset escalation on success
                self.last_success_time = time.time()

                # Update top news with saved articles
                scored_items = saved_items
                new_top_articles = []
                if self.top_news_mgr and saved_items:
                    try:
                        _, new_top_articles = self.top_news_mgr.update_top_news(saved_items)
                        scored_items = self.top_news_mgr.get_enriched_articles(saved_items)
                    except Exception as e:
                        print(f"[{self.scraper.name}] TOP_NEWS ERROR: {type(e).__name__}: {e}", flush=True)
                        self.log.warning(f"Top news update error: {e}")

                if self.mongo_storage and self.mongo_storage.available:
                    if scored_items:
                        try:
                            mongo_saved = self.mongo_storage.save_news(self.scraper.name, scored_items)
                            self.log.info(f"Saved {mongo_saved} in MongoDB")
                        except Exception as e:
                            print(f"[{self.scraper.name}] MONGO ERROR: {type(e).__name__}: {e}", flush=True)
                            self.log.warning(f"MongoDB save error: {e}")
                            
                    if new_top_articles:
                        try:
                            marked = self.mongo_storage.mark_as_top_news(new_top_articles)
                            if marked > 0:
                                self.log.info(f"Marked {marked} new historical top news in MongoDB")
                        except Exception as e:
                            print(f"[{self.scraper.name}] MONGO MARK ERROR: {type(e).__name__}: {e}", flush=True)
                            self.log.warning(f"MongoDB mark error: {e}")


                if self.redis:
                    self.redis.update_stats(self.scraper.name, saved)
                    self.redis.set_health(self.scraper.name, "healthy")
            else:
                self.consecutive_empty += 1
                # Throttled warning: only every 30 minutes
                now_ts = time.time()
                elapsed = now_ts - self.last_success_time
                if elapsed >= 1800 and (now_ts - self._last_empty_warn_time) >= 1800:
                    self._last_empty_warn_time = now_ts
                    self.log.warning(
                        f"No new data for {elapsed/60:.0f}m "
                        f"({self.consecutive_empty} fetches since last success)"
                    )
                # Check for blocked state
                elapsed = time.time() - self.last_success_time
                if elapsed > self.config.get("blocked_threshold_minutes", 120) * 60:
                    self._check_blocked()

            # Sleep with jitter
            delay = random.uniform(self.poll_min, self.poll_max)
            self.stop_event.wait(delay)

        self.log.info("Stopped")

    def _check_blocked(self):
        threshold = self.config.get("blocked_threshold_minutes", 120) * 60
        max_errors = self.config.get("max_consecutive_errors", 20)
        elapsed = time.time() - self.last_success_time

        if self.consecutive_errors >= max_errors or elapsed >= threshold:
            self.is_blocked = True
            self.block_count += 1
            self.log.blocked(
                f"BLOCKED — Site likely blocked our IP or access (Errors: {self.consecutive_errors}, "
                f"Silent for {elapsed/60:.0f}m, Level {self.block_count})"
            )
            if self.redis:
                self.redis.set_health(
                    self.scraper.name, "blocked",
                    f"errors={self.consecutive_errors}, silent={elapsed/60:.0f}m, "
                    f"level={self.block_count}",
                )

    def _blocked_delay(self) -> float:
        """Calculate blocked retry delay with exponential escalation + jitter."""
        base_min = self.config.get("blocked_delay_min", 5)
        base_max = self.config.get("blocked_delay_max", 15)
        factor = self.config.get("blocked_escalation_factor", 2)
        cap = self.config.get("blocked_max_delay_min", 120)

        # Escalate: base range × factor^(block_count-1), capped
        multiplier = factor ** max(0, self.block_count - 1)
        low = min(base_min * multiplier, cap)
        high = min(base_max * multiplier, cap)
        if low > high:
            low = high
        return random.uniform(low, high)

    def _backoff_sleep(self):
        backoff = min(30, self.poll_max * (1 + self.consecutive_errors * 0.3))
        self.stop_event.wait(backoff)


# ─── CLI Argument Parser ─────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for run modes."""
    parser = argparse.ArgumentParser(
        description="News Scrapper — multi-source news collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Run modes:
  (default)          Continuous polling with dashboard
  --once             Fetch once from all sources, then exit
  --cron SECONDS     Fetch, sleep N seconds, repeat (Ctrl+C to stop)
  --test             Quick connectivity test for each source
  --source NAME      Restrict to a single source (combine with any mode)
  --no-dash          Disable the dashboard server
""",
    )
    parser.add_argument(
        "--source", metavar="NAME",
        help="Run only this source (must match sites.yaml key)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run all enabled sources once, save results, then exit",
    )
    parser.add_argument(
        "--cron", type=int, metavar="SECONDS", default=None,
        help="Run sources, sleep SECONDS, repeat (like a cron job)",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Test mode — try each source once, report pass/fail, exit",
    )
    parser.add_argument(
        "--no-dash", action="store_true",
        help="Disable the dashboard HTTP server",
    )
    return parser.parse_args()


# ─── Run-mode helpers ────────────────────────────────────────────────────────

def _run_once(scrapers, storage, root_log, top_news_mgr=None, mongo_storage=None):
    """Fetch from each scraper once (sequentially) and save results."""
    categorizer = get_news_categorizer()
    total = 0
    for scraper in scrapers:
        try:
            scraper.setup()
            items = scraper.fetch_news()
        except Exception as e:
            root_log.error(f"[{scraper.name}] Fetch error: {e}")
            continue
        if items:
            for item in items:
                categorizer.apply_to_article(item)
            saved = storage.save_news(scraper.name, items)
            saved_items = items if saved > 0 else []

            scored_items = saved_items
            new_top_articles = []
            if top_news_mgr and saved_items:
                try:
                    _, new_top_articles = top_news_mgr.update_top_news(saved_items)
                    scored_items = top_news_mgr.get_enriched_articles(saved_items)
                except Exception as e:
                    root_log.warning(f"[{scraper.name}] Top-news update error: {e}")

            if mongo_storage and getattr(mongo_storage, "available", False):
                if scored_items:
                    try:
                        mongo_saved = mongo_storage.save_news(scraper.name, scored_items)
                        root_log.info(f"[{scraper.name}] +{mongo_saved} articles saved to MongoDB")
                    except Exception as e:
                        root_log.warning(f"[{scraper.name}] MongoDB save error: {e}")
                        
                if new_top_articles:
                    try:
                        marked = mongo_storage.mark_as_top_news(new_top_articles)
                        if marked > 0:
                            root_log.info(f"[{scraper.name}] +{marked} historical top news marked in MongoDB")
                    except Exception as e:
                        root_log.warning(f"[{scraper.name}] MongoDB mark top news error: {e}")

            total += saved
            root_log.info(f"[{scraper.name}] +{saved} articles saved")
        else:
            root_log.info(f"[{scraper.name}] 0 new articles")
    return total


def run_once_mode(scrapers, storage, root_log, top_news_mgr=None, mongo_storage=None):
    """--once: single fetch from all sources, then exit."""
    root_log.info("Mode: ONCE — fetching all sources once...")
    total = _run_once(scrapers, storage, root_log, top_news_mgr=top_news_mgr, mongo_storage=mongo_storage)
    root_log.info(f"Done. {total} total articles saved.")


def run_cron_mode(scrapers, storage, root_log, interval, config, top_news_mgr=None, mongo_storage=None):
    """--cron N: fetch, sleep N seconds, repeat until Ctrl+C."""
    root_log.info(f"Mode: CRON — interval {interval}s  (Ctrl+C to stop)")
    cycle = 0
    try:
        while True:
            # Quiet-hours gate
            if is_quiet_hours(config):
                root_log.info("Quiet hours — sleeping 60s...")
                time.sleep(60)
                continue
            cycle += 1
            root_log.info(f"--- Cron cycle {cycle} ---")
            total = _run_once(
                scrapers,
                storage,
                root_log,
                top_news_mgr=top_news_mgr,
                mongo_storage=mongo_storage,
            )
            root_log.info(f"Cycle {cycle} done. {total} articles. Sleeping {interval}s...")
            time.sleep(interval)
    except KeyboardInterrupt:
        root_log.info(f"Cron stopped after {cycle} cycles.")


def run_test_mode(scrapers, root_log):
    """--test: try each source once, report pass/fail, exit with code."""
    root_log.info("Mode: TEST — checking all sources...")
    passed = 0
    failed = 0
    results = []

    for scraper in scrapers:
        name = scraper.name
        try:
            scraper.setup()
            t0 = time.time()
            items = scraper.fetch_news()
            elapsed = time.time() - t0
            count = len(items) if items else 0

            if items:
                status = "PASS"
                passed += 1
                sample = items[0]["news_caption"][:60]
                root_log.info(
                    f"  [{name}] PASS — {count} items in {elapsed:.1f}s — \"{sample}\""
                )
            else:
                status = "WARN"
                passed += 1  # 0 items is not a crash, just empty
                root_log.info(
                    f"  [{name}] WARN — 0 items in {elapsed:.1f}s (source may be empty)"
                )
            results.append((name, status, count, f"{elapsed:.1f}s"))
        except Exception as e:
            failed += 1
            root_log.error(f"  [{name}] FAIL — {e}")
            results.append((name, "FAIL", 0, str(e)[:40]))

    # Summary table
    root_log.info("")
    root_log.info(f"{'Source':<18} {'Status':<8} {'Items':<8} {'Time/Error'}")
    root_log.info("-" * 56)
    for name, status, count, detail in results:
        root_log.info(f"{name:<18} {status:<8} {count:<8} {detail}")
    root_log.info("-" * 56)
    root_log.info(f"Total: {passed} passed, {failed} failed out of {len(scrapers)}")

    return 1 if failed else 0


# ─── Main Entry Point ───────────────────────────────────────────────────────

def main():
    args = parse_args()

    config = load_config()
    os.makedirs(config["data_dir"], exist_ok=True)
    os.makedirs(config["log_dir"], exist_ok=True)

    # Override dashboard if --no-dash or non-continuous mode
    if args.no_dash or args.once or args.cron is not None or args.test:
        config["dashboard_enabled"] = False

    # Logger
    logger = setup_logger(
        log_dir=config["log_dir"],
        log_level=config["log_level"],
    )
    root_log = SourceLogger(logger, "main")
    root_log.info(f"{'='*60}")
    root_log.info(f"  {config['project_name']} starting...")
    root_log.info(f"{'='*60}")

    # Show quiet-hours config
    qh_start = config.get("quiet_hours_start", "")
    qh_end = config.get("quiet_hours_end", "")
    if qh_start and qh_end:
        root_log.info(f"Quiet hours: {qh_start} – {qh_end} IST")
    else:
        root_log.info("Quiet hours: disabled")

    # Redis
    redis_cache = RedisCache(
        enabled=config["redis_enabled"],
        url=config["redis_url"],
        prefix=config["redis_prefix"],
        seen_ttl_days=config["redis_seen_ttl_days"],
    )

    # Proxy Manager
    proxy_manager = None
    if config["proxy_enabled"]:
        proxy_manager = ProxyManager(
            proxy_file=str(PROJECT_ROOT / config["proxy_file"]),
            bandwidth_limit_mb=config["proxy_bandwidth_limit_mb"],
            rotation=config["proxy_rotation"],
            redis_client=redis_cache._client if redis_cache.available else None,
            redis_prefix=config["redis_prefix"],
        )
        root_log.info(
            f"Proxies loaded: {proxy_manager.count} total, "
            f"{proxy_manager.available_count} available"
        )

    # Filter sources if --source specified
    sites_config = config["sites"]
    if args.source:
        if args.source not in sites_config:
            available = ", ".join(sites_config.keys())
            root_log.error(
                f"Source '{args.source}' not found in sites.yaml. "
                f"Available: {available}"
            )
            sys.exit(1)
        sites_config = {args.source: sites_config[args.source]}

    # Storage
    storage = JsonStorage(data_dir=config["data_dir"])
    migrated = storage.migrate_existing_source_data_to_daywise()
    root_log.info(f"Daywise storage mirror synchronized ({migrated} articles updated)")

    mongo_storage = MongoStorage(
        enabled=config["mongo_enabled"],
        mongo_url=config["mongo_url"],
        database_name=config["mongo_database"],
        collection_name=config["mongo_collection"],
        top_news_enabled=config["mongo_top_news_enabled"],
        top_news_collection_name=config["mongo_top_news_collection"],
        logger=logger,
    )

    # Build source importance weights from sites config
    source_weights = {}
    for source_name, source_cfg in config["sites"].items():
        weight = source_cfg.get("source_importance_weight", 1.0)
        source_weights[source_name] = weight

    # Shared categorizer instance for all ingestion paths.
    categorizer = get_news_categorizer()

    # Initialize top news manager
    semantic_config = {
        "enabled": config["semantic_enabled"],
        "cache_size": config["semantic_cache_size"],
        "model_name": config["semantic_model"],
        "fallback_model_name": config["semantic_fallback_model"],
        "max_length": 96,
        "semantic_text_chars": config["semantic_text_chars"],
        "ner_text_chars": config["ner_text_chars"],
        "spacy_enabled": config["spacy_enabled"],
        "spacy_model": config["spacy_model"],
        "recency_decay_hours": config["recency_decay_hours"],
        "dedup_top_n": config["topnews_dedup_top_n"],
        "heuristic_boost": True,
        "candidate_limit": config["semantic_candidate_limit"],
        "generate_json": config["generate_top_news_json"],
    }

    ranking_weights = {
        "semantic": config["rank_weight_semantic"],
        "entity": config["rank_weight_entity"],
        "event": config["rank_weight_event"],
        "recency": config["rank_weight_recency"],
        "source": config["rank_weight_source"],
    }

    top_news_mgr = get_top_news_manager(
        data_dir=config["data_dir"],
        source_weights=source_weights,
        ranking_weights=ranking_weights,
        semantic_config=semantic_config,
    )

    # Discover and instantiate scrapers
    scrapers = discover_scrapers(
        sites_config, config, proxy_manager, redis_cache
    )
    root_log.info(f"Loaded {len(scrapers)} scrapers: {[s.name for s in scrapers]}")

    if not scrapers:
        root_log.error("No scrapers enabled. Check sites.yaml")
        sys.exit(1)

    # ── Dispatch to the selected run mode ───────────────────────────
    if args.test:
        exit_code = run_test_mode(scrapers, root_log)
        sys.exit(exit_code)

    if args.once:
        run_once_mode(
            scrapers,
            storage,
            root_log,
            top_news_mgr=top_news_mgr,
            mongo_storage=mongo_storage,
        )
        return

    if args.cron is not None:
        run_cron_mode(
            scrapers,
            storage,
            root_log,
            args.cron,
            config,
            top_news_mgr=top_news_mgr,
            mongo_storage=mongo_storage,
        )
        return

    # ── Default: continuous polling mode ────────────────────────────
    # Stop event for graceful shutdown
    stop_event = threading.Event()
    start_time = time.time()

    # Start scraper worker threads
    workers: list[ScraperWorker] = []
    for scraper in scrapers:
        worker = ScraperWorker(
            scraper=scraper,
            storage=storage,
            redis_cache=redis_cache,
            mongo_storage=mongo_storage,
            config=config,
            stop_event=stop_event,
            top_news_mgr=top_news_mgr,
            categorizer=categorizer,
        )
        workers.append(worker)
        worker.start()

    # Start dashboard
    dashboard_server = None
    if config["dashboard_enabled"]:
        dashboard_server = start_dashboard(
            storage,
            workers,
            config,
            start_time,
            top_news_mgr=top_news_mgr,
        )
        if dashboard_server:
            host = config["dashboard_host"]
            port = config["dashboard_port"]
            root_log.info(f"Dashboard: http://{host}:{port}")

    # Signal handlers for graceful shutdown
    def shutdown_handler(signum, frame):
        root_log.info("Shutdown signal received...")
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown_handler)

    root_log.info("All systems running. Press Ctrl+C to stop.")

    # Keep main thread alive, print periodic status
    status_interval = 300  # log status every 5 minutes
    last_status = time.time()
    try:
        while not stop_event.is_set():
            stop_event.wait(1)  # short wait so Ctrl+C is responsive
            now = time.time()
            if not stop_event.is_set() and (now - last_status) >= status_interval:
                last_status = now
                alive = sum(1 for w in workers if w.is_alive())
                blocked = sum(1 for w in workers if w.is_blocked)
                total = sum(w.total_fetched for w in workers)
                root_log.info(
                    f"Status: {alive}/{len(workers)} alive, "
                    f"{blocked} blocked, {total} total articles"
                )
    except KeyboardInterrupt:
        pass

    # Graceful shutdown
    root_log.info("Shutting down all workers...")
    stop_event.set()

    for w in workers:
        w.join(timeout=15)

    if dashboard_server:
        dashboard_server.shutdown()

    if hasattr(top_news_mgr, "shutdown"):
        top_news_mgr.shutdown()

    root_log.info("Shutdown complete.")


if __name__ == "__main__":
    main()
