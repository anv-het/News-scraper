"""
Economic Times News Scraper
Source: https://economictimes.indiatimes.com/markets/stocks/news
Method: Primary: HTML page scraping (faster, more timely)
        Fallback: RSS feeds (slower but reliable)
Dedup: by news URL or msid
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .base import BaseScraper
from utils.time_utils import parse_rss_date, parse_iso_datetime, now_ist


class EconomicTimesScraper(BaseScraper):
    name = "economictimes"

    PAGE_URLS = [
        "https://economictimes.indiatimes.com/markets/stocks/news",
        "https://economictimes.indiatimes.com/markets/stocks/earnings",
        "https://economictimes.indiatimes.com/markets",
    ]

    RSS_FEEDS = [
        "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
        "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
        "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms",
    ]

    def setup(self):
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://economictimes.indiatimes.com/",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
        })
        self._page_index = 0

    def fetch_news(self) -> list[dict]:
        all_items = []

        # Primary: HTML page scraping (faster, more timely)
        html_items = self._fetch_html_pages()
        all_items.extend(html_items)

        # Fallback: RSS feeds only if HTML returned nothing
        if not html_items:
            self._log.debug("HTML scraping returned empty, falling back to RSS")
            all_items.extend(self._fetch_all_rss())

        return all_items

    def _fetch_html_pages(self) -> list[dict]:
        """Fetch news from HTML pages."""
        all_items = []

        # Fetch main stocks news page every time
        all_items.extend(self._fetch_html(self.PAGE_URLS[0]))

        # Rotate through other pages
        if len(self.PAGE_URLS) > 1:
            page_url = self.PAGE_URLS[1 + (self._page_index % (len(self.PAGE_URLS) - 1))]
            self._page_index += 1
            all_items.extend(self._fetch_html(page_url))

        return all_items

    def _fetch_html(self, url: str) -> list[dict]:
        """Scrape news from an ET page."""
        resp = self._safe_get(url)
        if not resp:
            return []

        try:
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            try:
                soup = BeautifulSoup(resp.text, "html.parser")
            except Exception:
                return []

        new_items = []
        new_ids = []

        # Pattern for article links
        article_pattern = re.compile(r"/markets/.*?/(\d{6,})\.cms$")

        # First pass: build URL -> image map
        url_to_image: dict[str, str] = {}
        for a_tag in soup.find_all("a", href=article_pattern):
            href = a_tag.get("href", "").strip()
            if not href:
                continue
            full_url = self._normalize_url(href)
            img = a_tag.find("img")
            if img:
                src = (img.get("src") or img.get("data-src") or "").strip()
                if src and full_url not in url_to_image:
                    if src.startswith("//"):
                        src = "https:" + src
                    url_to_image[full_url] = src

        # Also look for images in figure/picture tags near links
        for figure in soup.find_all(["figure", "picture", "div"]):
            img = figure.find("img")
            a_tag = figure.find("a", href=article_pattern)
            if img and a_tag:
                src = (img.get("src") or img.get("data-src") or "").strip()
                href = self._normalize_url(a_tag.get("href", ""))
                if src and href and href not in url_to_image:
                    if src.startswith("//"):
                        src = "https:" + src
                    url_to_image[href] = src

        # Second pass: extract articles
        seen_urls: set[str] = set()
        for a_tag in soup.find_all("a", href=article_pattern):
            href = a_tag.get("href", "").strip()
            if not href:
                continue

            news_url = self._normalize_url(href)
            if news_url in seen_urls:
                continue

            # Extract msid for dedup
            m = article_pattern.search(href)
            if not m:
                continue
            msid = m.group(1)
            if self._is_seen(msid):
                continue

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 15:
                # Try looking for title in parent
                parent = a_tag.parent
                if parent:
                    h_tag = parent.find(["h2", "h3", "h4"])
                    if h_tag:
                        title = h_tag.get_text(strip=True)
                if not title or len(title) < 15:
                    continue

            seen_urls.add(news_url)

            # Get image
            image_url = url_to_image.get(news_url, "")
            if not image_url:
                # Construct from msid
                image_url = f"https://img.etimg.com/thumb/msid-{msid},width-400,resizemode-4/{msid}.cms"

            # Try to extract time from data attributes or nearby time elements
            dt = None
            time_el = a_tag.find_parent().find("time") if a_tag.find_parent() else None
            if time_el:
                datetime_attr = time_el.get("datetime", "")
                if datetime_attr:
                    dt = parse_iso_datetime(datetime_attr)

            new_items.append(self._build_item(dt, title, "", news_url, image_url))
            new_ids.append(msid)

        self._mark_seen_bulk(new_ids)
        return new_items

    def _normalize_url(self, href: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("//"):
            return "https:" + href
        return "https://economictimes.indiatimes.com" + href

    def _fetch_all_rss(self) -> list[dict]:
        """Fetch ALL RSS feeds in parallel as fallback."""
        all_items = []
        with ThreadPoolExecutor(max_workers=len(self.RSS_FEEDS)) as executor:
            futures = {executor.submit(self._fetch_rss, url): url for url in self.RSS_FEEDS}
            for future in as_completed(futures):
                try:
                    items = future.result()
                    all_items.extend(items)
                except Exception as e:
                    url = futures[future]
                    self._log.debug(f"Failed to fetch {url}: {e}")
        return all_items

    def _fetch_rss(self, url: str) -> list[dict]:
        self.session.headers["Accept"] = "application/xml, text/xml, */*"
        resp = self._safe_get(url)
        if not resp:
            return []

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            return []

        new_items = []
        new_ids = []

        for item in root.findall(".//item"):
            link_el = item.find("link")
            if link_el is None or not link_el.text:
                continue
            news_url = link_el.text.strip()

            # Extract msid for dedup
            msid_match = re.search(r"/(\d{6,})\.cms", news_url)
            msid = msid_match.group(1) if msid_match else news_url
            if self._is_seen(msid):
                continue

            title_el = item.find("title")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")

            caption = self.clean_html(
                title_el.text.strip() if title_el is not None and title_el.text else ""
            )
            summary = self.clean_html(
                desc_el.text.strip() if desc_el is not None and desc_el.text else ""
            )
            pub_str = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
            dt = parse_rss_date(pub_str)

            # Extract image from media elements
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
            if not image_url:
                enc = item.find("enclosure")
                if enc is not None and enc.get("type", "").startswith("image/"):
                    image_url = enc.get("url", "")
            # Fallback: construct image from msid
            if not image_url and msid_match:
                image_url = f"https://img.etimg.com/thumb/msid-{msid},width-400,resizemode-4/{msid}.cms"

            new_items.append(self._build_item(dt, caption, summary, news_url, image_url))
            new_ids.append(msid)

        self._mark_seen_bulk(new_ids)
        return new_items
