"""
Times of India News Scraper
Source: https://timesofindia.indiatimes.com
Method: HTML scrape with embedded JSON data extraction
        TOI uses obfuscated CSS classes, so we extract from article links
        and construct image URLs from msid attributes.
Dedup: by article ID (from articleshow URL)
"""

import re

from bs4 import BeautifulSoup

from .base import BaseScraper
from utils.time_utils import now_ist


class TimesofIndiaScraper(BaseScraper):
    name = "timesofindia"

    PAGE_URL = "https://timesofindia.indiatimes.com"
    IMAGE_CDN = "https://static.toiimg.com/thumb/msid-{msid},width-400,resizemode-4/{msid}.jpg"

    def setup(self):
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "cross-site",
        })

    def fetch_news(self) -> list[dict]:
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
        new_items = []
        new_ids = []
        seen_ids = set()

        # TOI article URLs follow pattern: /articleshow/{id}.cms
        article_pattern = re.compile(r"articleshow/(\d+)\.cms")

        for a_tag in soup.find_all("a", href=article_pattern):
            href = a_tag.get("href", "")
            match = article_pattern.search(href)
            if not match:
                continue

            article_id = match.group(1)
            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)

            if self._is_seen(article_id):
                continue

            # Get title from link text, or parent elements
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 15:
                # Try finding text in a span child
                span = a_tag.find("span")
                if span:
                    title = span.get_text(strip=True)
            if not title or len(title) < 15:
                continue

            # Skip non-news links (ads, videos, etc.)
            if any(skip in href for skip in ("/videos/", "/tv/", "/live-tv/", "/etimes/", "/life-style/")):
                continue

            # Build full URL
            news_url = href
            if not news_url.startswith("http"):
                news_url = "https://timesofindia.indiatimes.com" + news_url

            # Extract image: TOI uses msid attribute on <img> tags
            image_url = ""
            # Check for img with msid in the parent container
            parent = a_tag.parent
            if parent:
                img_tag = parent.find("img", attrs={"msid": True})
                if img_tag:
                    msid = img_tag.get("msid", "")
                    if msid:
                        image_url = self.IMAGE_CDN.format(msid=msid)
                elif parent.find("img"):
                    img_tag = parent.find("img")
                    src = img_tag.get("src", "") or img_tag.get("data-src", "")
                    if src and "toiimg.com" in src:
                        image_url = src

            # If no image found from parent, construct from article ID
            if not image_url:
                image_url = self.IMAGE_CDN.format(msid=article_id)

            # TOI homepage doesn't show publish time per article
            dt = now_ist()

            new_items.append(self._build_item(dt, title, "", news_url, image_url))
            new_ids.append(article_id)

        self._mark_seen_bulk(new_ids)
        return new_items
