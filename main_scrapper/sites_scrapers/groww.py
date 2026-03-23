"""
Groww Stock News Scraper
Source: https://groww.in/market-news/stocks
Method: JSON API polling (20 items per page, cache-busted)
Dedup: by postId
"""

import time

from .base import BaseScraper
from utils.time_utils import parse_groww_date


class GrowwScraper(BaseScraper):
    name = "groww"

    API_BASE = (
        "https://groww.in/v2/api/feed/public"
        "?page=0&publisherId=stocknewssummary&size=20"
    )

    def setup(self):
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://groww.in/market-news/stocks",
            "x-platform": "web",
            "x-device-type": "desktop",
            "Cache-Control": "no-cache",
        })

    def fetch_news(self) -> list[dict]:
        # Cache-bust to bypass CDN's 5-minute max-age
        url = f"{self.API_BASE}&_ts={int(time.time())}"
        resp = self._safe_get(url, headers={"Accept": "application/json"})
        if not resp:
            return []

        try:
            data = resp.json()
        except ValueError:
            return []

        feed = data.get("feed", [])
        if not feed:
            return []

        new_items = []
        new_ids = []

        for item in feed:
            post_id = item.get("postId", "")
            if not post_id or self._is_seen(post_id):
                continue

            item_data = item.get("data", {})
            title = item_data.get("title", "").strip()
            if not title:
                continue

            body = item_data.get("body", "").strip()
            published_at = item.get("publishedAt", "")

            news_url = ""
            cta_list = item_data.get("cta", [])
            if cta_list and isinstance(cta_list, list):
                news_url = cta_list[0].get("ctaUrl", "")

            # Extract image if available
            image_url = ""
            img_list = item_data.get("images", [])
            if img_list and isinstance(img_list, list):
                image_url = img_list[0] if isinstance(img_list[0], str) else img_list[0].get("url", "")
            if not image_url:
                image_url = item_data.get("imageUrl", "") or item_data.get("image", "")

            dt = parse_groww_date(published_at)
            new_items.append(self._build_item(dt, title, body, news_url, image_url))
            new_ids.append(post_id)

        self._mark_seen_bulk(new_ids)
        return new_items
