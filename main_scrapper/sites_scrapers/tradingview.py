"""
TradingView News Scraper
Source: https://in.tradingview.com/news-flow
Method: Dual JSON API (India-specific + general en_IN) for maximum coverage
Dedup: by news ID
"""

import time

from .base import BaseScraper
from utils.time_utils import parse_timestamp


class TradingviewScraper(BaseScraper):
    name = "tradingview"

    # Two endpoints: India-specific (market_country=IN) and general (lang=en_IN)
    API_INDIA = (
        "https://news-mediator.tradingview.com/news-flow/v2/news"
        "?filter=lang%3Aen_IN&filter=market_country%3AIN"
        "&client=screener&streaming=true&user_prostatus=non_pro"
    )
    API_GENERAL = (
        "https://news-mediator.tradingview.com/news-flow/v2/news"
        "?filter=lang%3Aen_IN"
        "&client=screener&streaming=true&user_prostatus=non_pro"
    )

    def setup(self):
        self.session.headers.update({
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://in.tradingview.com/",
            "Origin": "https://in.tradingview.com",
            "Cache-Control": "no-cache",
        })

    def fetch_news(self) -> list[dict]:
        # Fetch both endpoints and merge results
        items_india = self._fetch_api(f"{self.API_INDIA}&_t={int(time.time())}")
        items_general = self._fetch_api(f"{self.API_GENERAL}&_t={int(time.time())}")
        return items_india + items_general

    def _fetch_api(self, url: str) -> list[dict]:
        resp = self._safe_get(url, timeout=(3, 5), stream=False)
        if not resp:
            return []

        try:
            data = resp.json()
        except ValueError:
            return []

        items = data.get("items", [])
        if not items:
            return []

        new_items = []
        new_ids = []

        for article in items:
            news_id = article.get("id", "")
            if not news_id or self._is_seen(str(news_id)):
                continue

            title = article.get("title", "").strip()
            if not title:
                continue

            news_url = article.get("link", "")
            if not news_url:
                story_path = article.get("storyPath", "")
                if story_path:
                    news_url = f"https://in.tradingview.com{story_path}"

            published_ts = article.get("published", 0)
            dt = parse_timestamp(published_ts)

            # Extract image
            image_url = article.get("image", "") or article.get("imageUrl", "")

            new_items.append(self._build_item(dt, title, "", news_url, image_url))
            new_ids.append(str(news_id))

        self._mark_seen_bulk(new_ids)
        return new_items
