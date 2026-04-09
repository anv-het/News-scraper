"""
Angel One News Scraper
Source: https://www.angelone.in/news
Method: Primary: Blog API (fast, reliable, has images and timestamps)
        Fallback: Sitemap XML (additional URLs)
Dedup: by article slug
Note: Session refresh every 3600s to prevent stale session blocks
"""

import re
import time
from xml.etree import ElementTree

from .base import BaseScraper
from utils.time_utils import parse_iso_datetime


class AngeloneScraper(BaseScraper):
    name = "angelone"

    BASE_URL = "https://www.angelone.in"
    API_URL = "https://kp-hl-httpapi-prod.angelone.in/public/v2/blog"
    SITEMAP_URL = "https://www.angelone.in/news-sitemap.xml"
    IMAGE_BASE_URL = "https://w3assets.angelone.in/"
    SESSION_REFRESH_INTERVAL = 3600  # Refresh session every 1 hour

    NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    ALLOWED_CATEGORIES = {
        "market-updates", "economy", "stocks", "mutual-funds",
        "commodities", "ipos", "global-market", "unlisted-companies",
    }

    def setup(self):
        self.session.headers.update({
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.angelone.in",
            "Referer": "https://www.angelone.in/",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        })

    def fetch_news(self) -> list[dict]:
        # Refresh session if it's been too long since last refresh
        if time.time() - self._session_created_at > self.SESSION_REFRESH_INTERVAL:
            self._log.info("Session refresh (periodic)")
            self._refresh_session()
            self.setup()  # Re-apply scraper-specific headers

        all_new = []

        # Primary: Blog API (fast, reliable, has timestamps + images)
        all_new.extend(self._fetch_api())

        # Secondary: sitemap for additional URLs
        all_new.extend(self._fetch_sitemap())

        return all_new

    def _fetch_api(self) -> list[dict]:
        """Fetch news from Angel One Blog API."""
        # Fetch more items to ensure we catch recent news
        resp = self._safe_get(f"{self.API_URL}?offset=0&limit=20")
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            self._log.warning("Failed to parse API JSON response")
            return []

        articles = data.get("data", [])
        if not isinstance(articles, list):
            return []

        new_items = []
        new_ids = []

        for article in articles:
            if not isinstance(article, dict):
                continue

            # Extract slug for dedup
            slug = (article.get("slug") or "").strip()
            if not slug or self._is_seen(slug):
                continue

            # Get title
            title = (article.get("title") or "").strip()
            if not title:
                continue

            # Get category and filter
            category = (article.get("category") or "").strip().lower()
            if category and category not in self.ALLOWED_CATEGORIES:
                continue

            # Build news URL
            news_url = f"{self.BASE_URL}/news/{category}/{slug}" if category else f"{self.BASE_URL}/news/{slug}"

            # Get summary/description
            summary = (article.get("description") or article.get("excerpt") or "").strip()

            # Parse published date (ISO format)
            pub_date = article.get("publishedAt") or article.get("createdAt") or ""
            dt = parse_iso_datetime(pub_date)

            # Build image URL - prepend base URL if it's a slug
            image_slug = (article.get("coverImage") or article.get("image") or "").strip()
            image_url = ""
            if image_slug:
                if image_slug.startswith("http"):
                    image_url = image_slug
                else:
                    # Remove leading slash if present
                    image_slug = image_slug.lstrip("/")
                    image_url = f"{self.IMAGE_BASE_URL}{image_slug}"

            new_items.append(self._build_item(dt, title, summary, news_url, image_url))
            new_ids.append(slug)

        self._mark_seen_bulk(new_ids)
        return new_items

    def _fetch_sitemap(self) -> list[dict]:
        """Fetch sitemap for additional URLs with lastmod timestamps."""
        resp = self._safe_get(self.SITEMAP_URL)
        if not resp:
            return []

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            return []

        new_items = []
        new_ids = []

        for url_el in root.findall("s:url", self.NS):
            loc = url_el.find("s:loc", self.NS)
            if loc is None or not loc.text:
                continue
            news_url = loc.text.strip()

            category = self._extract_category(news_url)
            if category and category not in self.ALLOWED_CATEGORIES:
                continue

            slug = news_url.rstrip("/").rsplit("/", 1)[-1]
            if not slug or self._is_seen(slug):
                continue

            lastmod = url_el.find("s:lastmod", self.NS)
            dt = None
            if lastmod is not None and lastmod.text:
                dt = parse_iso_datetime(lastmod.text.strip())

            # Derive readable title from slug
            caption = slug.replace("-", " ").title()
            if not caption:
                continue

            new_items.append(self._build_item(dt, caption, "", news_url))
            new_ids.append(slug)

        self._mark_seen_bulk(new_ids)
        return new_items

    @staticmethod
    def _extract_category(url: str) -> str:
        """Extract category from URL like /news/market-updates/slug -> market-updates."""
        m = re.search(r"/news/([^/]+)/", url)
        return m.group(1) if m else ""
