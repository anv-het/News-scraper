"""
CNBC TV18 News Scraper
Source: https://www.cnbctv18.com/
Method: JSON API (public endpoint, CORS open)
Dedup: by story_id
"""

from .base import BaseScraper
from utils.time_utils import parse_iso_datetime


class Cnbctv18Scraper(BaseScraper):
    name = "cnbctv18"

    API_URL = (
        "https://api-en.cnbctv18.com/nodeapi/v1/cne/get-article-list"
        "?count=50&offset=0"
        "&fields=story_id,display_headline,weburl_r,images,timetoread,"
        "created_at,updated_at"
        "&sortOrder=desc&sortBy=created_at"
    )

    def setup(self):
        self.session.headers.update({
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Origin": "https://www.cnbctv18.com",
            "Referer": "https://www.cnbctv18.com/",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        })

    def fetch_news(self) -> list[dict]:
        resp = self._safe_get(self.API_URL)
        if not resp:
            return []

        try:
            data = resp.json()
        except ValueError:
            self._log.warning(
                f"Non-JSON response ({len(resp.text)} bytes): "
                f"{resp.text[:200]}"
            )
            return []

        # The API may nest articles under various keys
        articles = []
        if isinstance(data, list):
            articles = data
        elif isinstance(data, dict):
            for key in ("data", "articles", "result", "items", "rows"):
                candidate = data.get(key)
                if isinstance(candidate, list) and candidate:
                    articles = candidate
                    break

        if not articles:
            self._log.debug("CNBCTV18 API returned no articles")
            return []

        new_items = []
        new_ids = []

        for article in articles:
            story_id = str(article.get("story_id", ""))
            if not story_id or self._is_seen(story_id):
                continue

            headline = (
                article.get("display_headline", "")
                or article.get("headline", "")
                or article.get("title", "")
            ).strip()
            if not headline:
                continue

            news_url = article.get("weburl_r", "") or ""
            if news_url and not news_url.startswith("http"):
                news_url = "https://www.cnbctv18.com" + news_url

            created_at = (
                article.get("created_at", "")
                or article.get("updated_at", "")
            )
            dt = parse_iso_datetime(created_at)

            # Extract thumbnail image
            image_url = ""
            images = article.get("images", {})
            if isinstance(images, dict):
                image_url = (
                    images.get("url", "")
                    or images.get("thumb", "")
                    or images.get("small", "")
                    or images.get("medium", "")
                    or images.get("large", "")
                )
            elif isinstance(images, list) and images:
                img = images[0]
                if isinstance(img, dict):
                    image_url = img.get("url", "") or img.get("thumb", "")
                elif isinstance(img, str):
                    image_url = img

            new_items.append(self._build_item(dt, headline, "", news_url, image_url))
            new_ids.append(story_id)

        self._mark_seen_bulk(new_ids)
        return new_items
