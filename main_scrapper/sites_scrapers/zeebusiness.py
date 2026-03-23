"""
Zee Business News Scraper
Source: https://www.zeebiz.com/
Method: Primary: Google News Sitemap XML (reliable, faster)
        Fallback: __NEXT_DATA__ from homepage (has images but more prone to blocking)
Dedup: by news URL
"""

import json
import re
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .base import BaseScraper
from utils.time_utils import parse_iso_datetime


class ZeeBusinessScraper(BaseScraper):
    name = "zeebusiness"

    PAGE_URL = "https://www.zeebiz.com/"
    SITEMAP_URL = "https://www.zeebiz.com/news-sitemap.xml"

    NS = {
        "s": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "n": "http://www.google.com/schemas/sitemap-news/0.9",
    }

    # Sections in __NEXT_DATA__ that contain news articles
    NEWS_SECTIONS = [
        "top_news", "markets", "stocks", "ipo", "commodities",
        "videos", "personal_finance", "banking", "insurance",
        "real_estate", "infra", "railways", "aviation",
    ]

    def setup(self):
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.zeebiz.com/",
            "sec-ch-ua": '"Chromium";v="145", "Google Chrome";v="145", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
        })

    def fetch_news(self) -> list[dict]:
        # Primary: sitemap (more reliable, less blocked)
        items = self._fetch_sitemap()
        if items:
            return items

        # Fallback: __NEXT_DATA__ from homepage (prone to anti-bot blocking)
        self._log.info("Sitemap empty, falling back to __NEXT_DATA__")
        return self._fetch_next_data()

    # ── Primary: __NEXT_DATA__ ─────────────────────────────────────────

    def _fetch_next_data(self) -> list[dict]:
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

        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return []

        try:
            raw = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            return []

        data = raw.get("props", {}).get("pageProps", {}).get("data", {})
        if not data:
            return []

        new_items = []
        new_ids = []

        for section_name in self.NEWS_SECTIONS:
            articles = data.get(section_name)
            if not isinstance(articles, list):
                continue

            for article in articles:
                websiteurl = (article.get("websiteurl") or "").strip()
                if not websiteurl:
                    continue
                if not websiteurl.startswith("http"):
                    websiteurl = "https://www.zeebiz.com" + websiteurl

                if self._is_seen(websiteurl):
                    continue

                title = (article.get("title") or "").strip()
                if not title:
                    continue

                # Parse timestamp (e.g. "1710580800" or ISO string)
                created = article.get("created", "")
                dt = None
                if created:
                    if isinstance(created, (int, float)):
                        from utils.time_utils import parse_timestamp
                        dt = parse_timestamp(int(created))
                    elif isinstance(created, str) and created.isdigit():
                        from utils.time_utils import parse_timestamp
                        dt = parse_timestamp(int(created))
                    else:
                        dt = parse_iso_datetime(created)

                image_url = (article.get("thumbnail_url") or "").strip()

                new_items.append(
                    self._build_item(dt, title, "", websiteurl, image_url)
                )
                new_ids.append(websiteurl)

        self._mark_seen_bulk(new_ids)
        return new_items

    # ── Fallback: Sitemap ──────────────────────────────────────────────

    def _fetch_sitemap(self) -> list[dict]:
        resp = self._safe_get(self.SITEMAP_URL)
        if not resp:
            return []

        xml_text = resp.text
        root = None
        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            fixed = self._fix_malformed_xml(xml_text)
            try:
                root = ElementTree.fromstring(fixed.encode("utf-8"))
            except ElementTree.ParseError:
                return self._regex_extract(xml_text)

        if root is None:
            return []

        new_items = []
        new_ids = []

        for url_el in root.findall("s:url", self.NS):
            loc = url_el.find("s:loc", self.NS)
            if loc is None or not loc.text:
                continue
            news_url = loc.text.strip()

            if self._is_seen(news_url):
                continue

            news_el = url_el.find("n:news", self.NS)
            if news_el is None:
                continue

            title_el = news_el.find("n:title", self.NS)
            pub_date_el = news_el.find("n:publication_date", self.NS)
            keywords_el = news_el.find("n:keywords", self.NS)

            caption = self.clean_html(
                title_el.text.strip() if title_el is not None and title_el.text else ""
            )
            if not caption:
                continue

            pub_str = pub_date_el.text.strip() if pub_date_el is not None and pub_date_el.text else ""
            dt = parse_iso_datetime(pub_str)
            summary = keywords_el.text.strip() if keywords_el is not None and keywords_el.text else ""

            new_items.append(self._build_item(dt, caption, summary, news_url))
            new_ids.append(news_url)

        self._mark_seen_bulk(new_ids)
        return new_items

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _fix_malformed_xml(xml_text: str) -> str:
        xml_text = re.sub(
            r'<!\[CDATA\[([^\]]*)\](?!\]>)',
            r'<![CDATA[\1]]>',
            xml_text,
        )
        xml_text = re.sub(
            r'<!\[CDATA\[(.*?)\]\s*</',
            r'<![CDATA[\1]]></',
            xml_text,
            flags=re.DOTALL,
        )
        return xml_text

    def _regex_extract(self, xml_text: str) -> list[dict]:
        new_items = []
        new_ids = []
        url_blocks = re.findall(r"<url>(.*?)</url>", xml_text, re.DOTALL)

        for block in url_blocks:
            loc_m = re.search(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", block)
            if not loc_m:
                continue
            news_url = loc_m.group(1).strip()
            if self._is_seen(news_url):
                continue

            title_m = re.search(
                r"<news:title>(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]?\]?>?)</news:title>",
                block, re.DOTALL,
            )
            date_m = re.search(
                r"<news:publication_date>\s*([^<]+?)\s*</news:publication_date>",
                block,
            )

            caption = self.clean_html(title_m.group(1).strip()) if title_m else ""
            if not caption:
                continue

            dt = parse_iso_datetime(date_m.group(1).strip()) if date_m else None
            new_items.append(self._build_item(dt, caption, "", news_url))
            new_ids.append(news_url)

        self._mark_seen_bulk(new_ids)
        return new_items
