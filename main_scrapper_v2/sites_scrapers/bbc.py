"""
BBC News Scraper
Source: https://www.bbc.com/news
Method: RSS feeds (3 feeds rotated: top stories, world, business)
Dedup: by article URL
"""

from xml.etree import ElementTree

from .base import BaseScraper
from utils.time_utils import parse_rss_date


class BbcScraper(BaseScraper):
    name = "bbc"

    RSS_FEEDS = [
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
    ]

    def setup(self):
        self.session.headers.update({
            "Accept": "application/xml, text/xml, */*",
            "Accept-Encoding": "gzip, deflate, br",
        })
        self._feed_index = 0

    def fetch_news(self) -> list[dict]:
        # Rotate through feeds each poll cycle
        feed_url = self.RSS_FEEDS[self._feed_index % len(self.RSS_FEEDS)]
        self._feed_index += 1

        resp = self._safe_get(feed_url)
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

            # Extract thumbnail from media:thumbnail
            image_url = ""
            for thumb in item.findall("{http://search.yahoo.com/mrss/}thumbnail"):
                image_url = thumb.get("url", "")
                if image_url:
                    break
            if not image_url:
                for content in item.findall("{http://search.yahoo.com/mrss/}content"):
                    if content.get("medium") == "image" or (content.get("url", "").endswith((".jpg", ".png", ".webp"))):
                        image_url = content.get("url", "")
                        if image_url:
                            break

            new_items.append(self._build_item(dt, caption, summary, news_url, image_url))
            new_ids.append(news_url)

        self._mark_seen_bulk(new_ids)
        return new_items
