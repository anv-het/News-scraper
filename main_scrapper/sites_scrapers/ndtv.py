"""
NDTV Latest News Scraper
Source: https://www.ndtv.com/latest
Method: Primary: FeedBurner RSS (updates every 1-5 min)
        Fallback: HTML scrape (server-rendered listing page)
Dedup: by article URL
"""

import re
from datetime import datetime
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .base import BaseScraper
from utils.time_utils import IST, parse_rss_date


class NdtvScraper(BaseScraper):
    name = "ndtv"

    # FeedBurner RSS updates every 1-5 minutes (much faster than HTML)
    RSS_URL = "https://feeds.feedburner.com/ndtvnews-latest"
    PAGE_URL = "https://www.ndtv.com/latest"

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
        # Primary: FeedBurner RSS (faster updates)
        items = self._fetch_rss()
        if items:
            return items

        # Fallback: HTML scrape
        self._log.debug("RSS returned empty, falling back to HTML scrape")
        return self._fetch_html()

    def _fetch_rss(self) -> list[dict]:
        """Fetch FeedBurner RSS feed (updates every 1-5 minutes)."""
        self.session.headers["Accept"] = "application/xml, text/xml, */*"
        resp = self._safe_get(self.RSS_URL)
        if not resp:
            return []

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            return []

        new_items = []
        new_ids = []

        for item in root.findall(".//item"):
            link = item.findtext("link") or item.findtext("guid") or ""
            link = link.strip()
            if not link:
                continue

            if self._is_seen(link):
                continue

            title = (item.findtext("title") or "").strip()
            if not title:
                continue

            summary = self.clean_html(item.findtext("description") or "")
            pub_str = (item.findtext("pubDate") or "").strip()
            dt = parse_rss_date(pub_str) if pub_str else None

            # Extract image from media:content or enclosure
            image_url = ""
            ns = {"media": "http://search.yahoo.com/mrss/"}
            media_content = item.find("media:content", ns)
            if media_content is not None:
                image_url = media_content.get("url", "")
            if not image_url:
                enclosure = item.find("enclosure")
                if enclosure is not None and enclosure.get("type", "").startswith("image/"):
                    image_url = enclosure.get("url", "")

            new_items.append(self._build_item(dt, title, summary, link, image_url))
            new_ids.append(link)

        self._mark_seen_bulk(new_ids)
        return new_items

    def _fetch_html(self) -> list[dict]:
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

        # NDTV /latest page uses <li class="NwsLstPg-a-li">
        items = soup.select("li.NwsLstPg-a-li")
        if not items:
            # Fallback: try generic article link extraction
            return self._fallback_extract(soup)

        for item in items:
            # Title and URL
            title_tag = item.select_one("h2.NwsLstPg_ttl a.NwsLstPg_ttl-lnk")
            if not title_tag:
                title_tag = item.select_one("h2 a")
            if not title_tag:
                continue

            news_url = title_tag.get("href", "").strip()
            if not news_url:
                continue
            if not news_url.startswith("http"):
                news_url = "https://www.ndtv.com" + news_url

            if self._is_seen(news_url):
                continue

            title = title_tag.get_text(strip=True)
            if not title:
                continue

            # Summary
            summary = ""
            summary_tag = item.select_one("p.NwsLstPg_txt")
            if summary_tag:
                summary = summary_tag.get_text(strip=True)

            # Date/time: "Mar 16, 2026 11:20 am IST"
            dt = None
            date_span = item.select_one("span.NwsLstPg_pst_lnk")
            if date_span:
                dt = self._parse_ndtv_date(date_span.get_text(strip=True))

            # Image
            image_url = ""
            img_tag = item.select_one("img.NwsLstPg_img-full")
            if not img_tag:
                img_tag = item.select_one("img")
            if img_tag:
                image_url = img_tag.get("src", "") or img_tag.get("data-src", "")

            new_items.append(self._build_item(dt, title, summary, news_url, image_url))
            new_ids.append(news_url)

        self._mark_seen_bulk(new_ids)
        return new_items

    def _fallback_extract(self, soup: BeautifulSoup) -> list[dict]:
        """Fallback: extract from generic article links on NDTV."""
        new_items = []
        new_ids = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            if not href or "ndtv.com" not in href:
                continue
            # Match news articles
            if not re.search(r"/(\w+-)+\d+$", href):
                continue
            if any(skip in href for skip in ("/video/", "/photos/", "/topic/")):
                continue

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 20:
                continue

            if self._is_seen(href):
                continue

            new_items.append(self._build_item(None, title, "", href))
            new_ids.append(href)

        self._mark_seen_bulk(new_ids)
        return new_items

    @staticmethod
    def _parse_ndtv_date(date_str: str) -> datetime | None:
        """Parse NDTV date like 'Mar 16, 2026 11:20 am IST'."""
        if not date_str:
            return None
        clean = date_str.replace(" IST", "").replace("Updated:", "").strip()
        for fmt in ("%b %d, %Y %I:%M %p", "%B %d, %Y %I:%M %p", "%b %d, %Y"):
            try:
                dt = datetime.strptime(clean, fmt)
                return dt.replace(tzinfo=IST)
            except ValueError:
                continue
        return None
