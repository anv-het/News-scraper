"""
ET Now News Scraper
Source: https://www.etnownews.com/
Method: Primary: Latest News API (fast, reliable, has images)
        Fallback: News sitemap
Dedup: by article msid
"""

import re
from xml.etree import ElementTree

from .base import BaseScraper
from utils.time_utils import parse_timestamp, parse_iso_datetime


class EtnowScraper(BaseScraper):
    name = "etnow"

    API_URL = "https://api.etnownews.com/api/latest"
    SITEMAP_URL = "https://www.etnownews.com/feeds/google-news-sitemap-etnow.xml"

    NS = {
        "s": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "n": "http://www.google.com/schemas/sitemap-news/0.9",
    }

    def setup(self):
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.etnownews.com",
            "Referer": "https://www.etnownews.com/",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        })

    def fetch_news(self) -> list[dict]:
        # Primary: Latest News API (fast, has images)
        items = self._fetch_api()
        if items:
            return items

        # Fallback: News sitemap
        self._log.debug("API returned empty, falling back to sitemap")
        return self._fetch_sitemap()

    def _fetch_api(self) -> list[dict]:
        """Fetch latest news from ET Now API."""
        params = {
            "seopath": "latest-news",
            "pageno": "1",
            "itemcount": "41",
            "origin": "desktop",
            "channel_id": "382",
        }

        url = f"{self.API_URL}?seopath={params['seopath']}&pageno={params['pageno']}&itemcount={params['itemcount']}&origin={params['origin']}&channel_id={params['channel_id']}"
        resp = self._safe_get(url)
        if not resp:
            return []

        try:
            data = resp.json()
        except Exception:
            self._log.warning("Failed to parse API JSON response")
            return []

        # Navigate to articles - API returns { data: { list: [...] } } or similar
        articles = []
        if isinstance(data, dict):
            # Try different possible structures
            if "data" in data:
                if isinstance(data["data"], list):
                    articles = data["data"]
                elif isinstance(data["data"], dict) and "list" in data["data"]:
                    articles = data["data"]["list"]
                elif isinstance(data["data"], dict) and "items" in data["data"]:
                    articles = data["data"]["items"]
            elif "list" in data:
                articles = data["list"]
            elif "items" in data:
                articles = data["items"]
            elif "articles" in data:
                articles = data["articles"]

        if not articles:
            self._log.debug("No articles found in API response")
            return []

        new_items = []

        for article in articles:
            if not isinstance(article, dict):
                continue

            # Extract msid for dedup
            msid = str(article.get("msid") or article.get("id") or "").strip()
            if not msid:
                continue

            # Get title
            title = (article.get("title") or article.get("headline") or "").strip()
            if not title:
                continue

            # Get synopsis/description
            synopsis = (article.get("synopsis") or article.get("description") or article.get("summary") or "").strip()

            # Build news URL
            seopath = article.get("seopath") or article.get("url") or ""
            if seopath:
                if seopath.startswith("http"):
                    news_url = seopath
                else:
                    news_url = f"https://www.etnownews.com/{seopath.lstrip('/')}"
            else:
                news_url = ""

            # Parse date - could be timestamp or ISO string
            dt = None
            update_ts = article.get("updatedate") or article.get("publishdate") or article.get("publishedAt") or 0
            if isinstance(update_ts, (int, float)) and update_ts > 0:
                # Handle millisecond timestamps
                dt = parse_timestamp(int(update_ts // 1000 if update_ts > 1e12 else update_ts))
            elif isinstance(update_ts, str):
                dt = parse_iso_datetime(update_ts)

            # Get image URL
            image_url = ""
            # Try different image field names
            img_src = (
                article.get("imageUrl") or
                article.get("image") or
                article.get("thumbnail") or
                article.get("thumbUrl") or
                ""
            )
            if img_src:
                if img_src.startswith("http"):
                    image_url = img_src
                elif img_src.startswith("//"):
                    image_url = "https:" + img_src
                else:
                    # Construct from msid if we have a relative path or msid
                    image_url = f"https://images.etnownews.com/thumb/msid-{msid},width-400,resizemode-4/{msid}.jpg"
            elif msid:
                # Default: construct from msid
                image_url = f"https://images.etnownews.com/thumb/msid-{msid},width-400,resizemode-4/{msid}.jpg"

            new_items.append(self._build_item(dt, title, synopsis, news_url, image_url))

        return new_items

    def _fetch_sitemap(self) -> list[dict]:
        """Fetch Google News sitemap as fallback."""
        self.session.headers["Accept"] = "application/xml, text/xml, */*"
        resp = self._safe_get(self.SITEMAP_URL)
        if not resp:
            return []

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            return []

        new_items = []

        for url_el in root.findall("s:url", self.NS):
            loc = url_el.find("s:loc", self.NS)
            if loc is None or not loc.text:
                continue
            news_url = loc.text.strip()

            # Extract msid from URL for dedup
            msid = self._extract_msid(news_url)
            if not msid:
                continue

            news_el = url_el.find("n:news", self.NS)
            if news_el is None:
                continue

            title_el = news_el.find("n:title", self.NS)
            pub_date_el = news_el.find("n:publication_date", self.NS)

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            if not title:
                continue

            dt = None
            if pub_date_el is not None and pub_date_el.text:
                dt = parse_iso_datetime(pub_date_el.text.strip())

            # Construct image URL from msid
            image_url = f"https://images.etnownews.com/thumb/msid-{msid},width-400,resizemode-4/{msid}.jpg"

            new_items.append(self._build_item(dt, title, "", news_url, image_url))

        return new_items

    def _extract_msid(self, url: str) -> str:
        """Extract msid from URL like /markets/article-title-123456.cms"""
        m = re.search(r"-(?:article|video)-(\d{6,})(?:$|[/?#])", url)
        if m:
            return m.group(1)
        m = re.search(r"-(\d{6,})\.cms$", url)
        if m:
            return m.group(1)
        # Also try plain numeric end
        m = re.search(r"/(\d{6,})$", url)
        return m.group(1) if m else ""
