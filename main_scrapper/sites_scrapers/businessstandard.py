"""
Business Standard News Scraper
Source: https://www.business-standard.com/latest-news
Method: __NEXT_DATA__ JSON extraction (Next.js SSR page)
Dedup: by article_id
"""

import json

from bs4 import BeautifulSoup

from .base import BaseScraper
from utils.time_utils import parse_timestamp


class BusinessstandardScraper(BaseScraper):
    name = "businessstandard"

    PAGE_URL = "https://www.business-standard.com/latest-news"

    def setup(self):
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.5",
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
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            try:
                soup = BeautifulSoup(resp.text, "html.parser")
            except Exception:
                return []

        return self._extract_from_next_data(soup)

    def _extract_from_next_data(self, soup: BeautifulSoup) -> list[dict]:
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            self._log.warning("No __NEXT_DATA__ found on Business Standard page")
            return self._extract_from_html(soup)

        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            self._log.warning("Failed to parse __NEXT_DATA__ JSON")
            return self._extract_from_html(soup)

        # Navigate to articles
        try:
            articles = data["props"]["pageProps"]["newsData"]
        except (KeyError, TypeError):
            self._log.warning("Unexpected __NEXT_DATA__ structure")
            return self._extract_from_html(soup)

        if not isinstance(articles, list):
            return self._extract_from_html(soup)

        new_items = []
        new_ids = []

        for article in articles:
            article_id = str(article.get("article_id", ""))
            if not article_id or self._is_seen(article_id):
                continue

            title = (article.get("heading1") or article.get("meta_title") or "").strip()
            if not title:
                continue

            summary = (article.get("sub_heading") or article.get("meta_description") or "").strip()

            article_url = article.get("article_url", "")
            news_url = article_url
            if news_url and not news_url.startswith("http"):
                news_url = "https://www.business-standard.com" + news_url

            # Parse published_date (Unix timestamp)
            pub_ts = article.get("published_date", 0)
            dt = None
            if pub_ts:
                dt = parse_timestamp(int(pub_ts) if isinstance(pub_ts, (int, float)) else 0)

            # Extract image
            image_url = ""
            media_maps = article.get("article_media_maps", [])
            if isinstance(media_maps, list) and media_maps:
                first_media = media_maps[0]
                if isinstance(first_media, dict):
                    image_url = (
                        first_media.get("image", "")
                        or first_media.get("fullImage", "")
                    )

            new_items.append(self._build_item(dt, title, summary, news_url, image_url))
            new_ids.append(article_id)

        self._mark_seen_bulk(new_ids)
        return new_items

    def _extract_from_html(self, soup: BeautifulSoup) -> list[dict]:
        """Fallback HTML extraction if __NEXT_DATA__ is unavailable."""
        new_items = []
        new_ids = []

        cards = soup.select("div.cardlist")
        for card in cards:
            title_tag = card.select_one("a.smallcard-title")
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            if not title:
                continue

            href = title_tag.get("href", "")
            news_url = href
            if news_url and not news_url.startswith("http"):
                news_url = "https://www.business-standard.com" + news_url

            if not news_url or self._is_seen(news_url):
                continue

            summary = ""
            summary_tag = card.select_one("p.bookreview-title")
            if summary_tag:
                summary = summary_tag.get_text(strip=True)

            # Extract image from noscript (Next.js lazy loading)
            image_url = ""
            noscript = card.find("noscript")
            if noscript:
                img = noscript.find("img")
                if img:
                    image_url = img.get("src", "")

            new_items.append(self._build_item(None, title, summary, news_url, image_url))
            new_ids.append(news_url)

        self._mark_seen_bulk(new_ids)
        return new_items
