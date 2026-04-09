"""
CNBC World Markets News Scraper
Source: https://www.cnbc.com/world-markets/
Method: Primary: RSS feed (reliable, no anti-bot protection)
        Secondary: window.__s_data JSON (has images but heavy anti-bot)
Dedup: by article URL
"""

import json
import re
from xml.etree import ElementTree

from .base import BaseScraper
from utils.time_utils import parse_iso_datetime, parse_rss_date


class CnbcScraper(BaseScraper):
    name = "cnbc"

    PAGE_URL = "https://www.cnbc.com/world-markets/"
    RSS_URL = (
        "https://search.cnbc.com/rs/search/combinedcms/view.xml"
        "?partnerId=wrss01&id=100003114"
    )

    def setup(self):
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.cnbc.com/",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
        })

    def fetch_news(self) -> list[dict]:
        # Primary: RSS feed (most reliable, no anti-bot protection)
        # CNBC.com uses heavy anti-bot (Akamai/reCAPTCHA) on HTML pages
        items = self._fetch_rss()
        if items:
            return items

        # Fallback: try __s_data (rarely succeeds due to anti-bot)
        self._log.debug("RSS returned empty, trying page scrape")
        return self._fetch_s_data()

    # ── Primary: window.__s_data ─────────────────────────────────────

    def _fetch_s_data(self) -> list[dict]:
        resp = self._safe_get(self.PAGE_URL)
        if not resp:
            return []

        m = re.search(r"window\.__s_data\s*=\s*(\{)", resp.text)
        if not m:
            return []

        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(resp.text[m.start(1):])
        except (json.JSONDecodeError, ValueError):
            return []

        page = data.get("page", {}).get("page", {})
        layout = page.get("layout", [])
        if not isinstance(layout, list):
            return []

        new_items = []
        new_ids = []

        for section in layout:
            columns = section.get("columns", [])
            for col in columns:
                if not isinstance(col, dict):
                    continue
                for mod in col.get("modules", []):
                    mod_data = mod.get("data", {})
                    if not isinstance(mod_data, dict):
                        continue
                    assets = mod_data.get("assets", [])
                    if not isinstance(assets, list):
                        continue
                    for asset in assets:
                        if not isinstance(asset, dict):
                            continue
                        self._process_asset(asset, new_items, new_ids)

        self._mark_seen_bulk(new_ids)
        return new_items

    def _process_asset(self, asset: dict, new_items: list, new_ids: list):
        url = (asset.get("url") or "").strip()
        if not url or self._is_seen(url):
            return

        title = (asset.get("title") or asset.get("headline") or "").strip()
        if not title:
            return

        # Skip videos/select
        if "/video/" in url or "/select/" in url:
            return

        desc = (asset.get("description") or "").strip()
        date_str = asset.get("datePublished", "")
        dt = parse_iso_datetime(date_str)

        image_url = ""
        promo = asset.get("promoImage")
        if isinstance(promo, dict):
            image_url = (promo.get("url") or "").strip()

        new_items.append(self._build_item(dt, title, desc, url, image_url))
        new_ids.append(url)

    # ── Fallback: RSS feed ───────────────────────────────────────────

    def _fetch_rss(self) -> list[dict]:
        self.session.headers["Accept"] = "application/xml, text/xml, */*"
        resp = self._safe_get(self.RSS_URL)
        if not resp:
            return []

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError as e:
            self._log.warning(f"RSS parse error: {e}")
            return []

        new_items = []
        new_ids = []

        for item in root.findall(".//item"):
            link_el = item.find("link")
            if link_el is None or not link_el.text:
                continue
            news_url = link_el.text.strip()

            if self._is_seen(news_url):
                continue

            title_el = item.find("title")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")

            caption = self.clean_html(
                title_el.text.strip()
                if title_el is not None and title_el.text else ""
            )
            summary = self.clean_html(
                desc_el.text.strip()
                if desc_el is not None and desc_el.text else ""
            )
            pub_str = (
                pub_el.text.strip()
                if pub_el is not None and pub_el.text else ""
            )
            dt = parse_rss_date(pub_str)

            if not caption:
                continue

            new_items.append(self._build_item(dt, caption, summary, news_url))
            new_ids.append(news_url)

        self._mark_seen_bulk(new_ids)
        return new_items
