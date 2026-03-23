"""
Rediff News Scraper
Source: https://www.rediff.com/news
Method: HTML scrape (article links + images) merged with RSS (dates + extra articles)
Dedup: by article URL
"""

import re
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .base import BaseScraper
from utils.time_utils import now_ist, parse_rss_date

_ARTICLE_RE = re.compile(
    r"rediff\.com/news/(report|column|special|interview|slide-show|commentary)/.*\.htm"
)

# Image URL patterns
_IMG_RE = re.compile(r"im\.rediff\.com")
_IMG_SIZE_RE = re.compile(r"/\d+-\d+/")


class RediffScraper(BaseScraper):
    name = "rediff"

    PAGE_URL = "https://www.rediff.com/news"
    RSS_URL = "https://www.rediff.com/rss/newsrss.xml"
    IMAGE_BASE = "https://im.rediff.com/430-250"

    def setup(self):
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://www.rediff.com/",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
        })

    def fetch_news(self) -> list[dict]:
        # Build image map from HTML page (has images but no dates)
        url_to_image = self._build_image_map()

        # Pull articles from RSS (has dates + summaries) merged with HTML
        rss_articles = self._fetch_rss()
        html_articles = self._fetch_html()

        # Merge: RSS articles take priority for dates, HTML fills images
        merged: dict[str, dict] = {}
        for art in html_articles:
            merged[art["url"]] = art
        for art in rss_articles:
            merged[art["url"]] = art  # RSS overwrites (better dates)

        new_items = []
        new_ids = []

        for url, art in merged.items():
            if self._is_seen(url):
                continue

            # Get image from multiple sources
            image_url = art.get("image") or url_to_image.get(url, "")

            # Normalize image URL to preferred 430-250 size
            if image_url:
                image_url = self._normalize_image_url(image_url)

            # Try to construct image URL from article URL if none found
            if not image_url:
                image_url = self._construct_image_url(url)

            dt = art.get("dt") or now_ist()
            new_items.append(
                self._build_item(dt, art["title"], art.get("summary", ""), url, image_url)
            )
            new_ids.append(url)

        self._mark_seen_bulk(new_ids)
        return new_items

    def _normalize_image_url(self, img_url: str) -> str:
        """Normalize image URL to use 430-250 size format."""
        if not img_url:
            return ""
        # Ensure https
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        # Replace size pattern with preferred 430-250
        if "im.rediff.com" in img_url:
            img_url = _IMG_SIZE_RE.sub("/430-250/", img_url)
        return img_url

    def _construct_image_url(self, article_url: str) -> str:
        """
        Try to construct image URL from article URL.
        Article: https://www.rediff.com/news/report/article-name/20260317.htm
        Image:   https://im.rediff.com/430-250/news/2026/mar/17article-name.jpg
        """
        # Extract path after /news/
        m = re.search(r"/news/(report|column|special|interview|slide-show|commentary)/([^/]+)/(\d{8})\.htm", article_url)
        if not m:
            return ""

        article_type = m.group(1)
        article_slug = m.group(2)
        date_str = m.group(3)  # e.g., '20260317'

        try:
            year = date_str[:4]
            month_num = int(date_str[4:6])
            day = date_str[6:8]

            # Convert month number to abbreviated name
            months = ["jan", "feb", "mar", "apr", "may", "jun",
                      "jul", "aug", "sep", "oct", "nov", "dec"]
            month = months[month_num - 1]

            # Construct image URL - try common patterns
            # Pattern: /430-250/news/2026/mar/17article-slug.jpg
            img_url = f"{self.IMAGE_BASE}/news/{year}/{month}/{day}{article_slug}.jpg"
            return img_url
        except (ValueError, IndexError):
            return ""

    def _build_image_map(self) -> dict[str, str]:
        """Fetch HTML page and build URL -> image map."""
        resp = self._safe_get(self.PAGE_URL)
        if not resp:
            return {}

        try:
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            try:
                soup = BeautifulSoup(resp.text, "html.parser")
            except Exception:
                return {}

        url_to_image: dict[str, str] = {}

        # Method 1: Find all image tags with im.rediff.com
        for img in soup.find_all("img", src=_IMG_RE):
            src = (img.get("src") or img.get("data-src") or "").strip()
            if not src or "rdefault.png" in src or "noimage" in src.lower():
                continue
            if src.startswith("//"):
                src = "https:" + src

            # Try to find associated article link
            # Check parent chain
            node = img
            for _ in range(6):  # Walk up to 6 levels
                if node.parent:
                    node = node.parent
                else:
                    break

                # Look for article links in this node
                for a_tag in node.find_all("a", href=_ARTICLE_RE):
                    href = self._norm_url(a_tag.get("href", ""))
                    if href and href not in url_to_image:
                        url_to_image[href] = self._normalize_image_url(src)
                        break

        # Method 2: Start from article links, look for images in same container
        for a_tag in soup.find_all("a", href=_ARTICLE_RE):
            href = self._norm_url(a_tag.get("href", ""))
            if not href or href in url_to_image:
                continue

            # Look for image in the link itself
            img = a_tag.find("img", src=_IMG_RE)
            if img:
                src = (img.get("src") or img.get("data-src") or "").strip()
                if src and "rdefault.png" not in src and "noimage" not in src.lower():
                    if src.startswith("//"):
                        src = "https:" + src
                    url_to_image[href] = self._normalize_image_url(src)
                    continue

            # Look in parent containers
            parent = a_tag.parent
            for _ in range(4):
                if not parent:
                    break
                img = parent.find("img", src=_IMG_RE)
                if img:
                    src = (img.get("src") or img.get("data-src") or "").strip()
                    if src and "rdefault.png" not in src and "noimage" not in src.lower():
                        if src.startswith("//"):
                            src = "https:" + src
                        url_to_image[href] = self._normalize_image_url(src)
                        break
                parent = parent.parent

        return url_to_image

    def _fetch_html(self) -> list[dict]:
        """Extract article links from HTML page."""
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

        articles = []
        seen: set[str] = set()

        for a_tag in soup.find_all("a", href=_ARTICLE_RE):
            url = self._norm_url(a_tag.get("href", ""))
            if not url or url in seen:
                continue

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 10:
                parent = a_tag.parent
                if parent:
                    h_tag = parent.find(["h2", "h3"])
                    if h_tag:
                        title = h_tag.get_text(strip=True)
                if not title or len(title) < 10:
                    continue

            seen.add(url)
            articles.append({"url": url, "title": title, "summary": "", "dt": None})

        return articles

    def _fetch_rss(self) -> list[dict]:
        """Fetch RSS feed for article dates and summaries."""
        self.session.headers["Accept"] = "application/xml, text/xml, */*"
        resp = self._safe_get(self.RSS_URL)
        if not resp:
            return []

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            return []

        articles = []
        for item in root.findall(".//item"):
            link = (item.findtext("link") or "").strip()
            url = self._norm_url(link)
            if not url:
                continue

            title = (item.findtext("title") or "").strip()
            if not title:
                continue

            summary = (item.findtext("description") or "").strip()
            pub_str = (item.findtext("pubDate") or "").strip()
            dt = parse_rss_date(pub_str) if pub_str else None

            # Try to get image from RSS enclosure or media:content
            image_url = ""
            enc = item.find("enclosure")
            if enc is not None:
                img_src = enc.get("url", "")
                if img_src and "im.rediff.com" in img_src:
                    image_url = self._normalize_image_url(img_src)

            # Check media:thumbnail
            for ns in ["{http://search.yahoo.com/mrss/}", ""]:
                thumb = item.find(f"{ns}thumbnail")
                if thumb is not None:
                    img_src = thumb.get("url", "")
                    if img_src and "im.rediff.com" in img_src:
                        image_url = self._normalize_image_url(img_src)
                        break

            articles.append({
                "url": url,
                "title": title,
                "summary": summary,
                "dt": dt,
                "image": image_url
            })

        return articles

    @staticmethod
    def _norm_url(href: str) -> str:
        href = href.strip()
        if not href:
            return ""
        if href.startswith("//"):
            href = "https:" + href
        elif not href.startswith("http"):
            href = "https://www.rediff.com" + href
        return href
