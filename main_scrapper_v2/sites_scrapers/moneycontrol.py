"""
MoneyControl Markets News Scraper
Source: https://www.moneycontrol.com/news/business/markets/
Method: HTML scrape (BeautifulSoup) — server-rendered <ul id="cagetory">
Dedup: by article ID extracted from URL
Note: RSS feeds are stale (last updated 2024), no usable JSON API found.
Note: Session refresh every 24 hours to prevent stale session blocks
"""

from bs4 import BeautifulSoup

from .base import BaseScraper
from utils.time_utils import now_ist


class MoneycontrolScraper(BaseScraper):
    name = "moneycontrol"

    PAGE_URL = "https://www.moneycontrol.com/news/business/markets/"
    SESSION_REFRESH_INTERVAL = 24 * 60 * 60  # Refresh session every 24 hours

    def setup(self):
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://www.moneycontrol.com/",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "upgrade-insecure-requests": "1",
        })

    def fetch_news(self) -> list[dict]:
        self._refresh_session_if_stale(self.SESSION_REFRESH_INTERVAL)

        resp = self._safe_get(self.PAGE_URL)
        if not resp:
            return []

        try:
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            try:
                soup = BeautifulSoup(resp.text, "html.parser")
            except Exception:
                return []

        return self._extract_news(soup)

    def _extract_news(self, soup: BeautifulSoup) -> list[dict]:
        # MoneyControl uses <ul id="cagetory"> (their actual typo) for the news list
        ul = soup.find("ul", id="cagetory")
        if not ul:
            return []

        items = ul.find_all(
            "li", class_="clearfix",
            id=lambda x: x and x.startswith("newslist-"),
        )

        new_items = []
        new_ids = []

        for li in items:
            a_tag = li.find("a")
            if not a_tag:
                continue

            news_url = a_tag.get("href", "").strip()
            if not news_url:
                continue

            # Article ID is the trailing number in the URL, e.g. ...release-13855013.html
            article_id = self._extract_id(news_url)
            if not article_id or self._is_seen(article_id):
                continue

            title = a_tag.get("title", "").strip()
            if not title:
                h2 = a_tag.find("h2")
                title = h2.get_text(strip=True) if h2 else ""
            if not title:
                continue

            # Summary from the first non-empty <p> directly inside <li>
            summary = ""
            for p in li.find_all("p", recursive=False):
                txt = p.get_text(strip=True)
                if txt:
                    summary = txt
                    break

            # MoneyControl doesn't embed publish time in the listing page,
            # so we use scrape time as the timestamp
            dt = now_ist()

            # Extract thumbnail image
            image_url = ""
            img_tag = li.find("img")
            if img_tag:
                image_url = img_tag.get("data-src", "") or img_tag.get("src", "")

            new_items.append(self._build_item(dt, title, summary, news_url, image_url))
            new_ids.append(article_id)

        self._mark_seen_bulk(new_ids)
        return new_items

    @staticmethod
    def _extract_id(url: str) -> str:
        """Extract the trailing numeric article ID from MoneyControl URLs."""
        # URL pattern: ...-13855013.html
        clean = url.rstrip("/").replace(".html", "")
        parts = clean.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[1]
        # Fallback: use the whole URL as ID
        return url
