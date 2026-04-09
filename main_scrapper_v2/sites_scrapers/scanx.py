"""
ScanX Stock Market News Scraper
Source: https://scanx.trade/stock-market-news
Method: HTML scrape (Angular SSR, ng-state JSON extraction) with ETag caching
Dedup: by article ID
"""

import json
import re

from .base import BaseScraper
from utils.time_utils import parse_iso_datetime

SUBCAT_TO_SLUG = {
    "corporate_action": "corporate-actions",
    "normal_news": "stocks",
    "order&deals": "orders-deals",
    "markets": "markets",
    "results": "earnings",
    "ipo": "ipo",
    "global": "global",
    "union_budget": "budget",
}


class ScanxScraper(BaseScraper):
    name = "scanx"

    PAGE_URL = "https://scanx.trade/stock-market-news"
    IMAGE_CDN = "https://news-images.dhan.co/"

    def setup(self):
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self._last_etag = ""

    def fetch_news(self) -> list[dict]:
        headers = {}
        if self._last_etag:
            headers["If-None-Match"] = self._last_etag

        resp = self._safe_get(self.PAGE_URL, headers=headers)
        if not resp:
            return []

        if resp.status_code == 304:
            return []

        etag = resp.headers.get("etag", "")
        if etag:
            self._last_etag = etag

        ng_state = self._extract_ng_state(resp.text)
        if not ng_state:
            return []

        return self._extract_articles(ng_state)

    def _extract_ng_state(self, html: str) -> dict | None:
        match = re.search(
            r'<script id="ng-state"[^>]*>(.*?)</script>', html, re.DOTALL
        )
        if not match:
            return None
        raw = match.group(1)
        raw = (
            raw.replace("&q;", '"')
            .replace("&l;", "<")
            .replace("&g;", ">")
            .replace("&a;", "&")
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _extract_articles(self, ng_state: dict) -> list[dict]:
        sections_data = None
        for v in ng_state.values():
            if not isinstance(v, dict):
                continue
            body = v.get("b", {})
            if isinstance(body, dict):
                data = body.get("data", {})
                if isinstance(data, dict) and "sections_data" in data:
                    sections_data = data["sections_data"]
                    break

        if not sections_data:
            return []

        new_items = []
        new_ids = []
        seen_batch: set[str] = set()

        for section in sections_data:
            for article in section.get("articles", []):
                aid = article.get("id")
                if not aid:
                    continue
                aid_str = str(aid)
                if aid_str in seen_batch or self._is_seen(aid_str):
                    continue

                title = article.get("articletitle", "").strip()
                if not title:
                    continue

                summary = article.get("summary", "").strip()
                pubdate = article.get("pubdate", "")
                news_url = self._build_url(article)
                dt = parse_iso_datetime(pubdate)

                # Extract image if available
                image_url = article.get("imageurl", "") or article.get("image", "")
                if image_url and not image_url.startswith("http"):
                    image_url = self.IMAGE_CDN + image_url

                new_items.append(self._build_item(dt, title, summary, news_url, image_url))
                seen_batch.add(aid_str)
                new_ids.append(aid_str)

        self._mark_seen_bulk(new_ids)
        return new_items

    @staticmethod
    def _build_url(article: dict) -> str:
        subcat = article.get("subcategory", "")
        slug = article.get("slug", "")
        aid = article.get("id", "")
        path_seg = SUBCAT_TO_SLUG.get(subcat, subcat)
        if slug and aid:
            return f"https://scanx.trade/stock-market-news/{path_seg}/{slug}/{aid}"
        return ""
