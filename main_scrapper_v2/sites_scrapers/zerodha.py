"""
Zerodha Pulse News Scraper
Source: https://pulse.zerodha.com/
Method: HTML scrape (BeautifulSoup)
Dedup: by news URL
"""

from bs4 import BeautifulSoup

from .base import BaseScraper
from utils.time_utils import parse_zerodha_date


class ZerodhaScraper(BaseScraper):
    name = "zerodha"

    BASE_URL = "https://pulse.zerodha.com/"

    def setup(self):
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://pulse.zerodha.com/",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "upgrade-insecure-requests": "1",
        })

    def fetch_news(self) -> list[dict]:
        resp = self._safe_get(self.BASE_URL)
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
        items = soup.select("li.box.item")
        new_items = []
        new_ids = []

        for item in items:
            # Main article
            title_tag = item.select_one("h2.title > a")
            if not title_tag:
                continue

            url = title_tag.get("href", "").strip()
            caption = title_tag.get_text(strip=True)
            summary = ""
            desc_tag = item.select_one("div.desc")
            if desc_tag:
                summary = desc_tag.get_text(strip=True)

            date_span = item.find("span", class_="date", recursive=False)
            date_title = date_span.get("title", "") if date_span else ""
            dt = parse_zerodha_date(date_title)

            if url and not self._is_seen(url):
                # Extract image from main article
                image_url = ""
                img_tag = item.select_one("img")
                if img_tag:
                    image_url = img_tag.get("data-src", "") or img_tag.get("src", "")

                new_items.append(self._build_item(dt, caption, summary, url, image_url))
                new_ids.append(url)

            # Similar / related articles
            for sim in item.select("ul.similar > li"):
                sim_a = sim.select_one("a.title2")
                if not sim_a:
                    continue
                sim_url = sim_a.get("href", "").strip()
                sim_caption = sim_a.get_text(strip=True)

                sim_date_span = sim.find("span", class_="date")
                sim_date_title = (
                    sim_date_span.get("title", "") if sim_date_span else ""
                )
                sim_dt = parse_zerodha_date(sim_date_title)

                if sim_url and not self._is_seen(sim_url):
                    new_items.append(
                        self._build_item(sim_dt, sim_caption, "", sim_url)
                    )
                    new_ids.append(sim_url)

        self._mark_seen_bulk(new_ids)
        return new_items
