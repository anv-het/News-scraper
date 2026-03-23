"""
Reuters News Scraper
Source: https://www.reuters.com/
Method: Arc Publishing outbound news sitemap (XML) — not behind DataDome
        Fetches latest 100 articles per call from the news sitemap endpoint.
        Falls back to paginated sitemaps (from=100, 200, ...) on rotation.
Dedup: by article canonical URL
Note: reuters.com pages/API are behind DataDome anti-bot (JS challenge),
      but the Arc outbound feeds are publicly accessible.
"""

import re
import xml.etree.ElementTree as ET

import requests

from .base import BaseScraper
from utils.time_utils import parse_iso_datetime


class ReutersScraper(BaseScraper):
    name = "reuters"

    # Arc Publishing news sitemap — returns ~100 articles per page
    SITEMAP_BASE = "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml"

    # XML namespaces used in the sitemap
    NS = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "news": "http://www.google.com/schemas/sitemap-news/0.9",
        "image": "http://www.google.com/schemas/sitemap-image/1.1",
    }

    def setup(self):
        self._page_index = 0  # rotate through sitemap pages
        self.session.headers.update({
            "Accept": "application/xml, text/xml, */*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch_news(self) -> list[dict]:
        # Page 0 = latest 100, page 1 = from=100, etc.
        page = self._page_index % 3  # only check first 300 articles
        self._page_index += 1

        url = self.SITEMAP_BASE
        if page > 0:
            url += f"&from={page * 100}"

        resp = self._safe_get(url, timeout=(5, 15))
        if resp is None:
            return []

        text = resp.text
        if len(text) < 200 or "<?xml" not in text[:100]:
            self._log.warning(
                f"Non-XML response ({len(text)} bytes) from sitemap"
            )
            return []

        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            self._log.warning(f"Sitemap XML parse error: {e}")
            return []

        return self._parse_sitemap(root)

    def _parse_sitemap(self, root: ET.Element) -> list[dict]:
        """Extract articles from a Reuters news sitemap XML."""
        new_items, new_ids = [], []

        for url_elem in root.findall("sm:url", self.NS):
            loc = url_elem.find("sm:loc", self.NS)
            if loc is None or not loc.text:
                continue

            news_url = loc.text.strip()
            if self._is_seen(news_url):
                continue

            # Extract news metadata
            news_elem = url_elem.find("news:news", self.NS)
            if news_elem is None:
                continue

            title_elem = news_elem.find("news:title", self.NS)
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
            if not title:
                continue

            pub_date_elem = news_elem.find("news:publication_date", self.NS)
            pub_date = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else ""
            dt = parse_iso_datetime(pub_date)

            # Use keywords as summary (stock tickers can be informative too)
            keywords_elem = news_elem.find("news:keywords", self.NS)
            stock_elem = news_elem.find("news:stock_tickers", self.NS)

            summary_parts = []
            if stock_elem is not None and stock_elem.text:
                tickers = stock_elem.text.strip()
                if tickers:
                    summary_parts.append(f"Tickers: {tickers}")

            summary = " | ".join(summary_parts)

            # Extract image from sitemap <image:image> element
            image_url = ""
            image_elem = url_elem.find("image:image", self.NS)
            if image_elem is not None:
                image_loc = image_elem.find("image:loc", self.NS)
                if image_loc is not None and image_loc.text:
                    image_url = image_loc.text.strip()

            new_items.append(self._build_item(dt, title, summary, news_url, image_url))
            new_ids.append(news_url)

        self._mark_seen_bulk(new_ids)
        return new_items
