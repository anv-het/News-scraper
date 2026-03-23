"""
Time utilities for IST conversion, formatting, and time_ago computation.
All datetimes are handled in IST (UTC+5:30).
"""

import re
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)


def format_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def format_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p") + " IST"


def format_scraped_at() -> str:
    return now_ist().strftime("%Y-%m-%d %I:%M:%S %p") + " IST"


def time_ago_str(dt: datetime | None) -> str:
    """Human-readable time difference from now."""
    if dt is None:
        return ""
    diff = now_ist() - dt
    seconds = int(diff.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now" if seconds < 10 else f"{seconds} seconds ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hr ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def sort_key_desc(item: dict) -> str:
    """Generate sortable key from news_date + news_time for descending order."""
    date = item.get("news_date", "")
    time_str = item.get("news_time", "").replace(" IST", "").strip()
    if date and time_str:
        try:
            dt = datetime.strptime(f"{date} {time_str}", "%Y-%m-%d %I:%M %p")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return date


def parse_iso_datetime(date_str: str) -> datetime | None:
    """Parse various ISO datetime formats to IST datetime."""
    if not date_str:
        return None
    try:
        # Handle Z suffix
        clean = date_str.replace("Z", "+00:00")
        # Handle +0530 without colon
        clean = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", clean)
        dt = datetime.fromisoformat(clean)
        return dt.astimezone(IST)
    except (ValueError, TypeError):
        return None


def parse_rss_date(date_str: str) -> datetime | None:
    """Parse RSS pubDate like 'Sat, 07 Mar 2026 11:00:19 +0530' or with named TZ."""
    if not date_str:
        return None

    date_str = date_str.strip()

    # Named timezone mappings to UTC offset (in hours)
    TZ_MAP = {
        "EDT": -4, "EST": -5,  # Eastern
        "CDT": -5, "CST": -6,  # Central
        "MDT": -6, "MST": -7,  # Mountain
        "PDT": -7, "PST": -8,  # Pacific
        "UTC": 0, "GMT": 0, "Z": 0,
        "IST": 5.5,  # Indian Standard Time
    }

    # Replace named timezone with numeric offset
    for tz_name, offset in TZ_MAP.items():
        if date_str.endswith(f" {tz_name}"):
            sign = "+" if offset >= 0 else "-"
            hours = int(abs(offset))
            mins = int((abs(offset) - hours) * 60)
            offset_str = f"{sign}{hours:02d}{mins:02d}"
            date_str = date_str[:-len(tz_name)-1] + " " + offset_str
            break

    try:
        dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        return dt.astimezone(IST)
    except ValueError:
        pass

    # Try without seconds
    try:
        dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M %z")
        return dt.astimezone(IST)
    except ValueError:
        return None


def parse_timestamp(ts: int) -> datetime | None:
    """Convert Unix timestamp to IST datetime."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=IST)
    except (ValueError, OSError):
        return None


def parse_groww_date(date_str: str) -> datetime | None:
    """Parse Groww publishedAt like '2026-03-08T10:57:03' (already IST)."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=IST)
    except (ValueError, TypeError):
        return None


def parse_zerodha_date(date_title: str) -> datetime | None:
    """Parse Zerodha date like '08:38 AM, 07 Mar 2026'."""
    if not date_title:
        return None
    try:
        dt = datetime.strptime(date_title.strip(), "%I:%M %p, %d %b %Y")
        return dt.replace(tzinfo=IST)
    except ValueError:
        return None


def parse_stockedge_datetime(date_str: str, time_str: str = "") -> datetime | None:
    """
    Parse StockEdge Date + Time fields.
    Date: '2026-03-09T00:00:00'   Time: '03:45 pm'
    """
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        if time_str:
            t = datetime.strptime(time_str.strip(), "%I:%M %p")
            dt = dt.replace(hour=t.hour, minute=t.minute)
        return dt.replace(tzinfo=IST)
    except (ValueError, TypeError):
        return None


def parse_angelone_date(date_str: str) -> datetime | None:
    """Parse Angel One date like '9 March 2026'."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%d %B %Y")
        return dt.replace(tzinfo=IST)
    except (ValueError, TypeError):
        return None
