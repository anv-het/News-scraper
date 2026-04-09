"""
LiveMint News Scraper
Source: https://www.livemint.com/latest-news
Method: JSON API (fast, ~3-5s) + 9 RSS feeds (broad, ~45s sweep)
Dedup: by news URL
"""

import random
import time
from xml.etree import ElementTree

from .base import BaseScraper
from utils.time_utils import parse_iso_datetime, parse_rss_date


class LivemintScraper(BaseScraper):
    name = "livemint"

    API_LATEST = "https://www.livemint.com/api/cms/story/latest?limit=50"

    RSS_FEEDS = [
        "https://www.livemint.com/rss/news",
        "https://www.livemint.com/rss/companies",
        "https://www.livemint.com/rss/markets",
        "https://www.livemint.com/rss/industry",
        "https://www.livemint.com/rss/politics",
        "https://www.livemint.com/rss/opinion",
        "https://www.livemint.com/rss/money",
        "https://www.livemint.com/rss/budget",
        "https://www.livemint.com/rss/elections",
    ]

    RSS_INTERVAL = 18  # full sweep every ~18s
    FEED_DELAY = (0.1, 0.3)

    def setup(self):
        self.session.headers.update({
            "Accept": "*/*",
            "Referer": "https://www.livemint.com/",
        })
        self._last_rss_time = 0.0
        self._rss_index = 0

    def fetch_news(self) -> list[dict]:
        all_new = []

        # Fast path: API latest
        all_new.extend(self._fetch_api())

        # Slow path: one RSS feed per cycle
        now = time.monotonic()
        if now - self._last_rss_time >= self.RSS_INTERVAL / len(self.RSS_FEEDS):
            feed_url = self.RSS_FEEDS[self._rss_index]
            all_new.extend(self._fetch_rss(feed_url))
            self._rss_index = (self._rss_index + 1) % len(self.RSS_FEEDS)
            self._last_rss_time = now

        return all_new

    def _fetch_api(self) -> list[dict]:
        resp = self._safe_get(self.API_LATEST)
        if not resp:
            return []

        try:
            data = resp.json()
        except ValueError:
            return []

        new_items = []
        new_ids = []

        for article in data.get("content", []):
            meta = article.get("metadata", {})
            url_path = meta.get("url", "")
            if not url_path:
                continue
            news_url = "https://www.livemint.com" + url_path

            if self._is_seen(news_url):
                continue

            headline = self.clean_html(article.get("headline", ""))
            summary = self.clean_html(article.get("summary", ""))
            pub_date = article.get("firstPublishedDate", "")
            dt = parse_iso_datetime(pub_date)

            # Extract hero image
            image_url = ""
            hero = article.get("heroImage", {})
            if isinstance(hero, dict):
                image_url = hero.get("imageUrl", "") or hero.get("url", "")
            if not image_url:
                image_url = meta.get("imageUrl", "") or meta.get("thumbnailUrl", "")

            new_items.append(self._build_item(dt, headline, summary, news_url, image_url))
            new_ids.append(news_url)

        self._mark_seen_bulk(new_ids)
        return new_items

    def _fetch_rss(self, url: str) -> list[dict]:
        resp = self._safe_get(url)
        if not resp:
            return []

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            return []

        new_items = []
        new_ids = []

        for item in root.findall(".//item"):
            link_el = item.find("link")
            if link_el is None or not link_el.text:
                continue
            news_url = link_el.text.strip()

            if self._is_seen(news_url):
                continue

            title_el = item.find("title")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")

            caption = self.clean_html(
                title_el.text.strip() if title_el is not None and title_el.text else ""
            )
            summary = self.clean_html(
                desc_el.text.strip() if desc_el is not None and desc_el.text else ""
            )
            pub_str = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
            dt = parse_rss_date(pub_str)

            new_items.append(self._build_item(dt, caption, summary, news_url))
            new_ids.append(news_url)

        self._mark_seen_bulk(new_ids)
        return new_items
