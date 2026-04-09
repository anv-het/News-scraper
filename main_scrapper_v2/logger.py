"""
Professional colored logging with file output.
Provides structured, timestamped, color-coded console output
and rotating file logs for long-running operation.
"""

import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

IST = timezone(timedelta(hours=5, minutes=30))


class ISTFormatter(logging.Formatter):
    """Formatter that uses IST timezone."""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=IST)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class ColoredFormatter(ISTFormatter):
    """Colored console formatter with pipe-separated format."""

    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    LEVEL_NAMES = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def format(self, record):
        color = self.COLORS.get(record.levelno, Fore.WHITE)
        level_name = self.LEVEL_NAMES.get(record.levelno, "UNKNOWN")
        ts = self.formatTime(record)
        date_part = ts.split(" ")[0]  # YYYY-MM-DD
        time_part = ts.split(" ")[1]  # HH:MM:SS

        source = getattr(record, "source", "")
        source_str = source if source else "-"

        msg = record.getMessage()

        # Format: 2026-03-25| 14:21:32| INFO| Zeebusiness | Message
        return (
            f"{Fore.WHITE}{date_part}{Style.RESET_ALL}"
            f"{Fore.WHITE}|{Style.RESET_ALL} "
            f"{Fore.WHITE}{time_part}{Style.RESET_ALL}"
            f"{Fore.WHITE}|{Style.RESET_ALL} "
            f"{color}{Style.BRIGHT}{level_name}{Style.RESET_ALL}"
            f"{Fore.WHITE}|{Style.RESET_ALL} "
            f"{Fore.MAGENTA}{source_str}{Style.RESET_ALL}"
            f"{Fore.WHITE}|{Style.RESET_ALL} "
            f"{color}{msg}{Style.RESET_ALL}"
        )


class FileFormatter(ISTFormatter):
    """Plain text file formatter with pipe-separated format."""

    def format(self, record):
        ts = self.formatTime(record)
        date_part = ts.split(" ")[0]  # YYYY-MM-DD
        time_part = ts.split(" ")[1]  # HH:MM:SS
        level = record.levelname
        source = getattr(record, "source", "")
        source_str = source if source else "-"

        # Format: 2026-03-25| 14:21:32| INFO| Zeebusiness | Message
        msg = record.getMessage()
        return f"{date_part}| {time_part}| {level}| {source_str} | {msg}"


def setup_logger(
    log_dir: str = "logs",
    log_level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB per file
    backup_count: int = 10,
) -> logging.Logger:
    """
    Set up the application logger with colored console + date-time based file output.

    Returns the root 'scrapper' logger. Child loggers are created per-source
    via get_source_logger().
    """
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("scrapper")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()

    # Console handler (colored)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ColoredFormatter())
    logger.addHandler(console)

    # Main log file with date-time timestamp
    now = datetime.now(IST)
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    main_log_path = os.path.join(log_dir, f"scrapper.{timestamp}.log")

    main_file = logging.FileHandler(main_log_path, encoding="utf-8")
    main_file.setFormatter(FileFormatter())
    logger.addHandler(main_file)

    # Error-only log file
    error_file = RotatingFileHandler(
        os.path.join(log_dir, "errors.log"),
        maxBytes=max_bytes,
        backupCount=5,
        encoding="utf-8",
    )
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(FileFormatter())
    logger.addHandler(error_file)

    # Blocked sites log
    blocked_handler = RotatingFileHandler(
        os.path.join(log_dir, "blocked.log"),
        maxBytes=max_bytes,
        backupCount=5,
        encoding="utf-8",
    )
    blocked_handler.setLevel(logging.WARNING)
    blocked_handler.setFormatter(FileFormatter())
    blocked_handler.addFilter(BlockedFilter())
    logger.addHandler(blocked_handler)

    return logger


class BlockedFilter(logging.Filter):
    """Only allows records tagged as blocked events."""

    def filter(self, record):
        return getattr(record, "blocked", False)


class SourceLogger:
    """
    Convenience wrapper that injects 'source' into log records.
    Use: slog = SourceLogger(logger, "groww")
         slog.info("Found 5 new articles")
    """

    def __init__(self, logger: logging.Logger, source: str):
        self._logger = logger
        self._source = source

    def _log(self, level: int, msg: str, **kwargs):
        extra = {"source": self._source}
        extra.update(kwargs.get("extra", {}))
        self._logger.log(level, msg, extra=extra)

    def debug(self, msg: str, **kw):
        self._log(logging.DEBUG, msg, **kw)

    def info(self, msg: str, **kw):
        self._log(logging.INFO, msg, **kw)

    def warning(self, msg: str, **kw):
        self._log(logging.WARNING, msg, **kw)

    def error(self, msg: str, **kw):
        self._log(logging.ERROR, msg, **kw)

    def critical(self, msg: str, **kw):
        self._log(logging.CRITICAL, msg, **kw)

    def blocked(self, msg: str):
        """Log a blocked-site event (goes to blocked.log)."""
        self._logger.log(
            logging.WARNING,
            msg,
            extra={"source": self._source, "blocked": True},
        )
