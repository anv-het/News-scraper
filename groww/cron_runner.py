"""
Cross-platform Cron Runner for Groww News Fetcher

Runs fetch_news.py on a schedule defined in .env:
  - CRON_DAY_GAP: days between runs
  - CRON_START_TIME / CRON_END_TIME: random execution within this window
  - Auto-refreshes the stocks list before each news run

Works on both Windows and Linux (uses time.sleep, no OS-specific schedulers).

Usage:
    python cron_runner.py
"""

import random
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path

from config import get_config
from logger import setup_logger, get_logger


def parse_time(time_str: str) -> tuple:
    """Parse HH:MM string into (hour, minute)."""
    parts = time_str.strip().split(":")
    return int(parts[0]), int(parts[1])


def get_random_run_time(start_str: str, end_str: str, target_date: datetime) -> datetime:
    """
    Generate a random datetime between start_time and end_time on target_date.

    Args:
        start_str: Start time as "HH:MM"
        end_str: End time as "HH:MM"
        target_date: The date to schedule on

    Returns:
        Random datetime within the window
    """
    sh, sm = parse_time(start_str)
    eh, em = parse_time(end_str)

    start_dt = target_date.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end_dt = target_date.replace(hour=eh, minute=em, second=0, microsecond=0)

    if end_dt <= start_dt:
        raise ValueError(f"CRON_END_TIME ({end_str}) must be after CRON_START_TIME ({start_str})")

    # Random seconds within the window
    delta_seconds = int((end_dt - start_dt).total_seconds())
    random_offset = random.randint(0, delta_seconds)
    return start_dt + timedelta(seconds=random_offset)


def run_stocks_update(logger):
    """Refresh the stocks list by running fetch_stocks."""
    logger.info("Refreshing stocks list...")
    try:
        from fetch_stocks import GrowwStockFetcher
        fetcher = GrowwStockFetcher()
        success = fetcher.run()
        if success:
            logger.info("Stocks list updated successfully")
        else:
            logger.warning("Stocks update had issues, but continuing with existing data")
        return success
    except Exception as e:
        logger.error(f"Stocks update failed: {e}")
        return False


def run_news_fetch(logger):
    """Run the news fetcher."""
    logger.info("Starting news fetch...")
    try:
        from fetch_news import GrowwNewsFetcher
        fetcher = GrowwNewsFetcher()
        return fetcher.run()
    except Exception as e:
        logger.error(f"News fetch failed: {e}")
        return False


def main():
    config = get_config()
    setup_logger(log_level=config.logging.level, log_to_file=config.logging.log_to_file)
    logger = get_logger("cron_runner")

    if not config.cron.enabled:
        logger.error("Cron is disabled. Set CRON_ENABLED=true in .env")
        return 1

    logger.info("=" * 60)
    logger.info("Groww Cron Runner — Started")
    logger.info(f"  Day gap:     {config.cron.day_gap} day(s)")
    logger.info(f"  Time window: {config.cron.start_time} — {config.cron.end_time}")
    logger.info("=" * 60)

    while True:
        try:
            now = datetime.now()

            # Determine the next run date
            # If we're still within today's window, schedule today; otherwise, schedule next cycle
            sh, sm = parse_time(config.cron.start_time)
            eh, em = parse_time(config.cron.end_time)
            today_end = now.replace(hour=eh, minute=em, second=0, microsecond=0)

            if now < today_end:
                target_date = now
            else:
                target_date = now + timedelta(days=config.cron.day_gap)

            # Pick a random time within the window
            run_time = get_random_run_time(
                config.cron.start_time,
                config.cron.end_time,
                target_date,
            )

            # If the random time is in the past (e.g., we just started and it's already 3 PM),
            # pick a new random time between now and end
            if run_time <= datetime.now():
                remaining_end = target_date.replace(hour=eh, minute=em, second=0, microsecond=0)
                if remaining_end > datetime.now():
                    remaining_seconds = int((remaining_end - datetime.now()).total_seconds())
                    if remaining_seconds > 60:
                        run_time = datetime.now() + timedelta(seconds=random.randint(60, remaining_seconds))
                    else:
                        # Less than a minute left in window, push to next day
                        target_date = datetime.now() + timedelta(days=config.cron.day_gap)
                        run_time = get_random_run_time(
                            config.cron.start_time,
                            config.cron.end_time,
                            target_date,
                        )
                else:
                    target_date = datetime.now() + timedelta(days=config.cron.day_gap)
                    run_time = get_random_run_time(
                        config.cron.start_time,
                        config.cron.end_time,
                        target_date,
                    )

            # Wait until the scheduled time
            wait_seconds = (run_time - datetime.now()).total_seconds()
            if wait_seconds > 0:
                logger.info(f"Next run scheduled at: {run_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"Sleeping for {wait_seconds / 3600:.1f} hours...")

                # Sleep in chunks so KeyboardInterrupt works cleanly
                sleep_end = time.time() + wait_seconds
                while time.time() < sleep_end:
                    remaining = sleep_end - time.time()
                    time.sleep(min(remaining, 60))

            # Execute the run
            logger.info("=" * 60)
            logger.info(f"CRON RUN — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 60)

            # Step 1: Refresh stocks list
            run_stocks_update(logger)

            # Step 2: Fetch news
            run_news_fetch(logger)

            logger.info("Cron run complete.")

            # Schedule next run
            next_date = datetime.now() + timedelta(days=config.cron.day_gap)
            next_run = get_random_run_time(
                config.cron.start_time,
                config.cron.end_time,
                next_date,
            )
            wait_seconds = (next_run - datetime.now()).total_seconds()
            logger.info(f"Next run: {next_run.strftime('%Y-%m-%d %H:%M:%S')} "
                         f"(in {wait_seconds / 3600:.1f} hours)")

            sleep_end = time.time() + wait_seconds
            while time.time() < sleep_end:
                remaining = sleep_end - time.time()
                time.sleep(min(remaining, 60))

        except KeyboardInterrupt:
            logger.info("\nCron stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.info("Retrying in 5 minutes...")
            time.sleep(300)

    return 0


if __name__ == "__main__":
    sys.exit(main())
