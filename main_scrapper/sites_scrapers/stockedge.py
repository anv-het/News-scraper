"""
StockEdge News Scraper
Source: https://web.stockedge.com/daily-updates?section=news
Method: JSON API polling (paginated, 2 pages of 30 items each)
Dedup: by ID

API response shape (list of dicts):
    ID, Date, Time, Caption, Description, Details,
    SubSectionName, NewsitemSecurities, NewsitemSectors, NewsitemIndustries
"""

from .base import BaseScraper
from utils.time_utils import parse_stockedge_datetime


class StockedgeScraper(BaseScraper):
    name = "stockedge"

    API_BASE = (
        "https://api.stockedge.com/Api/DailyDashboardApi/GetLatestNewsItems"
        "?page={page}&pageSize=20&sectionType=null&lang=en"
    )
    PAGES = [1, 2, 3]  # Fetch 3 pages (60 items) for broader coverage

    def setup(self):
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://web.stockedge.com/",
            "Origin": "https://web.stockedge.com",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
        })

    def fetch_news(self) -> list[dict]:
        import time
        import random
        all_new = []
        for i, page in enumerate(self.PAGES):
            all_new.extend(self._fetch_page(page))
            # Add delay between page fetches to avoid rate limiting
            if i < len(self.PAGES) - 1:
                time.sleep(random.uniform(1.5, 3.0))
        return all_new

    def _fetch_page(self, page: int) -> list[dict]:
        url = self.API_BASE.format(page=page)
        resp = self._safe_get(url)
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

        if isinstance(data, dict) and "message" in data:
            self._log.warning(
                f"API error response: {data.get('message', '')} "
                f"(status: {data.get('statusCode', '?')})"
            )
            return []

        if not isinstance(data, list):
            return []

        if not data:
            return []

        new_items = []
        new_ids = []

        for item in data:
            news_id = str(item.get("ID", ""))
            if not news_id or self._is_seen(news_id):
                continue

            caption = (item.get("Description") or "").strip()
            if not caption:
                caption = (item.get("Caption") or "").strip()
            if not caption:
                continue

            summary = self.clean_html(item.get("Details") or "")

            # Unique URL per item (ID in fragment) so storage dedup works correctly
            news_url = f"https://web.stockedge.com/daily-updates?section=news#id={news_id}"

            date_str = item.get("Date", "")
            time_str = item.get("Time", "")
            dt = parse_stockedge_datetime(date_str, time_str)

            # Extract security logo as image (no article-level images available)
            image_url = ""
            securities = item.get("NewsitemSecurities") or []
            if isinstance(securities, list):
                for sec in securities:
                    logo = sec.get("SecurityLogoUrl", "")
                    if logo and not logo.endswith(".svg"):
                        image_url = logo
                        break
                    elif logo:
                        image_url = logo
                        break
            if not image_url:
                industries = item.get("NewsitemIndustries") or []
                if isinstance(industries, list):
                    for ind in industries:
                        img = ind.get("IndustryImageUrl", "")
                        if img:
                            image_url = img
                            break

            new_items.append(self._build_item(dt, caption, summary, news_url, image_url))
            new_ids.append(news_id)

        self._mark_seen_bulk(new_ids)
        return new_items
