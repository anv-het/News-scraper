"""
Top news management with synchronous real-time impact scoring.

Pipeline:
  Scraper -> Per-item impact scoring -> Exact-title top-N dedup -> Ranked output
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time

from utils.time_utils import now_ist
from categorizing.config import (
    DEFAULT_RANKING_WEIGHTS,
    DEFAULT_SEMANTIC_CONFIG,
    DEFAULT_SOURCE_WEIGHTS,
    TOP_NEWS_BOOST_KEYWORDS,
)
from categorizing.realtime_impact import RealTimeImpactScorer


class TopNewManager:
    """Thread-safe top-news manager with real-time impact scoring."""

    def __init__(
        self,
        data_dir: str = "DATA",
        logger=None,
        source_weights: dict | None = None,
        ranking_weights: dict | None = None,
        semantic_config: dict | None = None,
    ):
        self.data_dir = data_dir
        self.logger = logger or logging.getLogger("top_news")
        self.source_weights = source_weights or DEFAULT_SOURCE_WEIGHTS
        self.semantic_config = {**DEFAULT_SEMANTIC_CONFIG, **(semantic_config or {})}
        self.ranking_weights = {**DEFAULT_RANKING_WEIGHTS, **(ranking_weights or {})}
        self.generate_json = bool(self.semantic_config.get("generate_json", True))

        self._lock = threading.Lock()
        self._top_news: list[dict] = []
        self._article_index: dict[str, dict] = {}
        self._historical_top_ids: set[str] = set()

        self._top_news_dir = os.path.join(data_dir, "top_news")
        self._top_news_file = os.path.join(self._top_news_dir, "top_news.json")
        self._historical_csv_file = os.path.join(self._top_news_dir, "historical_top_news_ids.csv")
        self._candidate_limit = int(self.semantic_config.get("candidate_limit", 4000))
        self._dedup_top_n = bool(self.semantic_config.get("dedup_top_n", True))

        os.makedirs(self._top_news_dir, exist_ok=True)

        self._impact_scorer = RealTimeImpactScorer(
            source_weights=self.source_weights,
            ranking_weights=self.ranking_weights,
            runtime_config=self.semantic_config,
            logger=self.logger,
        )
        self.ranking_weights = self._impact_scorer.ranking_weights

        self._load_top_news()
        self._load_historical_top_news()

    def shutdown(self) -> None:
        """Compatibility no-op for graceful shutdown hooks."""
        return

    def _load_top_news(self) -> None:
        if not os.path.exists(self._top_news_file):
            return

        try:
            with open(self._top_news_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self._top_news = data.get("articles", [])
            self._article_index = {self._get_article_id(item): dict(item) for item in self._top_news}
            self.logger.debug(f"Loaded {len(self._top_news)} top news articles")
        except Exception as exc:
            self.logger.error(f"Failed to load top news: {exc}")
            self._top_news = []
            self._article_index = {}

    def _load_historical_top_news(self) -> None:
        """Load historically seen top news IDs from CSV into memory."""
        if not os.path.exists(self._historical_csv_file):
            return
            
        try:
            with open(self._historical_csv_file, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if parts and parts[0]:
                        self._historical_top_ids.add(parts[0])
            self.logger.debug(f"Loaded {len(self._historical_top_ids)} historical top news IDs from CSV")
        except Exception as exc:
            self.logger.error(f"Failed to load historical top news CSV: {exc}")

    def _save_top_news(self) -> None:
        if not self.generate_json:
            return

        data = {
            "articles": self._top_news,
            "last_updated": now_ist().isoformat(),
            "algorithm_version": "3.0-realtime-impact",
            "ranking_weights": self.ranking_weights,
            "semantic_enabled": bool(self.semantic_config.get("enabled", True)),
        }

        fd, tmp_path = tempfile.mkstemp(dir=self._top_news_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)

            attempts = 5
            for index in range(attempts):
                try:
                    if os.path.exists(self._top_news_file):
                        os.replace(tmp_path, self._top_news_file)
                    else:
                        os.rename(tmp_path, self._top_news_file)
                    break
                except PermissionError:
                    if index == attempts - 1:
                        raise
                    time.sleep(0.05 * (2 ** index))
        except Exception as exc:
            self.logger.error(f"Failed to save top news: {exc}")
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _calculate_time_score(self, article: dict) -> float:
        return self._impact_scorer.calculate_recency_score(article)

    def _calculate_keyword_boost(self, article: dict) -> float:
        title = (article.get("news_caption") or article.get("title") or "").lower()
        summary = (article.get("news_summary") or article.get("content") or "").lower()

        boost = 0.0
        for keyword, weight in TOP_NEWS_BOOST_KEYWORDS.items():
            if keyword in title:
                boost += weight * 1.4
            elif keyword in summary:
                boost += weight

        return min(1.2, boost)

    def _calculate_keyword_score(self, article: dict) -> float:
        return min(1.0, self._calculate_keyword_boost(article) / 1.2)

    def _get_source_weight(self, article: dict) -> float:
        source = (article.get("source") or "").lower().strip()
        return self.source_weights.get(source, 1.0)

    def _calculate_source_score(self, article: dict) -> float:
        return self._impact_scorer.calculate_source_score(article)

    def _combine_scores(
        self,
        semantic_score: float,
        keyword_score: float,
        entity_score: float,
        event_score: float,
        recency_score: float,
        source_score: float,
    ) -> float:
        return self._impact_scorer.combine_scores(
            semantic_score=semantic_score,
            keyword_score=keyword_score,
            entity_score=entity_score,
            event_score=event_score,
            recency_score=recency_score,
            source_score=source_score,
        )

    def calculate_relevance_score(self, article: dict) -> float:
        semantic_score = float(article.get("semantic_score", 0.0) or 0.0)
        keyword_score = float(article.get("keyword_score", 0.0) or 0.0)
        entity_score = float(article.get("entity_score", 0.0) or 0.0)
        event_score = float(article.get("event_score", 0.0) or 0.0)

        if semantic_score <= 0 and entity_score <= 0 and event_score <= 0:
            breakdown = self._impact_scorer.score_item(article)
            semantic_score = breakdown.semantic_score
            keyword_score = breakdown.keyword_score
            entity_score = breakdown.entity_score
            event_score = breakdown.event_score

        recency_score = self._calculate_time_score(article)
        source_score = self._calculate_source_score(article)
        return self._combine_scores(
            semantic_score=semantic_score,
            keyword_score=keyword_score,
            entity_score=entity_score,
            event_score=event_score,
            recency_score=recency_score,
            source_score=source_score,
        )

    def _get_article_id(self, article: dict) -> str:
        source = article.get("source", "unknown")
        url = article.get("news_url", "")
        return hashlib.sha256(f"{source}:{url}".encode()).hexdigest()

    def _apply_fresh_scores_locked(self, article: dict) -> dict:
        needs_full = any(
            key not in article
            for key in (
                "semantic_score",
                "entity_score",
                "event_score",
                "semantic_anchor",
            )
        )

        enriched = dict(article)
        if needs_full:
            breakdown = self._impact_scorer.score_item(enriched)
            enriched["semantic_score"] = breakdown.semantic_score
            enriched["keyword_score"] = breakdown.keyword_score
            enriched["entity_score"] = breakdown.entity_score
            enriched["event_score"] = breakdown.event_score
            enriched["recency_score"] = breakdown.recency_score
            enriched["source_score"] = breakdown.source_score
            enriched["score"] = breakdown.final_score
            enriched["semantic_anchor"] = breakdown.semantic_anchor
            enriched["entities"] = {
                "ORG": breakdown.entities_org,
                "PERSON": breakdown.entities_person,
                "GPE": breakdown.entities_gpe,
            }
            enriched["event_matches"] = breakdown.events
        else:
            semantic_score = float(enriched.get("semantic_score", 0.0) or 0.0)
            keyword_score = float(enriched.get("keyword_score", 0.0) or 0.0)
            entity_score = float(enriched.get("entity_score", 0.0) or 0.0)
            event_score = float(enriched.get("event_score", 0.0) or 0.0)
            recency_score = self._calculate_time_score(enriched)
            source_score = self._calculate_source_score(enriched)

            enriched["keyword_score"] = keyword_score
            enriched["recency_score"] = recency_score
            enriched["source_score"] = source_score
            enriched["score"] = self._combine_scores(
                semantic_score=semantic_score,
                keyword_score=keyword_score,
                entity_score=entity_score,
                event_score=event_score,
                recency_score=recency_score,
                source_score=source_score,
            )

        enriched["ranked_at"] = now_ist().isoformat()
        return enriched

    def _trim_article_index_locked(self) -> None:
        if len(self._article_index) <= self._candidate_limit:
            return

        ranked = sorted(
            self._article_index.values(),
            key=self.calculate_relevance_score,
            reverse=True,
        )
        keep_ids = {self._get_article_id(item) for item in ranked[: self._candidate_limit]}
        self._article_index = {
            article_id: article
            for article_id, article in self._article_index.items()
            if article_id in keep_ids
        }

    @staticmethod
    def _deduplicate_titles(scored_articles: list[dict], top_n: int) -> list[dict]:
        unique: list[dict] = []
        seen_titles: set[str] = set()

        for article in scored_articles:
            title = (article.get("news_caption") or article.get("title") or "").strip()
            if title in seen_titles:
                continue
            seen_titles.add(title)
            unique.append(article)
            if len(unique) >= top_n:
                break

        return unique

    def _recompute_top_news_locked(self) -> None:
        scored_articles: list[dict] = []

        for article_id, article in self._article_index.items():
            enriched = self._apply_fresh_scores_locked(article)
            enriched["id"] = article_id
            enriched["title"] = (enriched.get("news_caption") or enriched.get("title") or "")[:100]
            enriched["source"] = enriched.get("source", "")
            enriched["category"] = enriched.get("category", "Others")
            scored_articles.append(enriched)

        scored_articles.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        if self._dedup_top_n:
            self._top_news = self._deduplicate_titles(scored_articles, top_n=100)
        else:
            self._top_news = scored_articles[:100]
            
        new_top_news = []
        for article in self._top_news:
            uid = str(article.get("unique_id") or self._get_article_id(article)).strip()
            if uid and uid not in self._historical_top_ids:
                new_top_news.append(article)
                
        return new_top_news

    def _append_to_historical_csv(self, newly_crowned: list[dict]) -> None:
        """Append newly crowned top news IDs to the historical CSV."""
        if not newly_crowned:
            return
            
        try:
            with open(self._historical_csv_file, "a", encoding="utf-8") as f:
                for article in newly_crowned:
                    uid = str(article.get("unique_id") or self._get_article_id(article)).strip()
                    ts = article.get("ranked_at", now_ist().isoformat())
                    f.write(f"{uid},{ts}\n")
                    self._historical_top_ids.add(uid)
        except Exception as exc:
            self.logger.error(f"Failed to append to historical top news CSV: {exc}")

    def update_top_news(self, articles: list[dict]) -> tuple[list[dict], list[dict]]:
        if not articles:
            return self._top_news, []

        newly_crowned = []
        with self._lock:
            for article in articles:
                article_id = self._get_article_id(article)
                existing = self._article_index.get(article_id, {})
                merged = {**existing, **article}
                merged = self._apply_fresh_scores_locked(merged)
                self._article_index[article_id] = merged

            self._trim_article_index_locked()
            newly_crowned = self._recompute_top_news_locked()
            self._append_to_historical_csv(newly_crowned)
            self._save_top_news()

        if self._top_news:
            self.logger.info(
                f"Updated top news: {len(self._top_news)} articles, min score={self._top_news[-1].get('score', 0.0):.4f}"
            )
            
        if newly_crowned:
            self.logger.info(f"Added {len(newly_crowned)} new articles to historical top news")

        return self._top_news, newly_crowned

    def get_enriched_articles(self, articles: list[dict]) -> list[dict]:
        """Return scored article snapshots from the internal index."""
        if not articles:
            return []

        enriched_articles: list[dict] = []
        with self._lock:
            for article in articles:
                article_id = self._get_article_id(article)
                indexed = self._article_index.get(article_id)
                if indexed is None:
                    indexed = self._apply_fresh_scores_locked(dict(article))
                    self._article_index[article_id] = indexed
                enriched_articles.append(dict(indexed))

        return enriched_articles

    def get_top_news(self, limit: int = 100, category: str | None = None) -> list[dict]:
        with self._lock:
            articles = self._top_news
            if category:
                articles = [item for item in articles if item.get("category", "Others") == category]

            if self._dedup_top_n:
                articles = self._deduplicate_titles(articles, top_n=max(1, limit))
            return articles[:limit]

    def get_top_news_by_category(self) -> dict:
        with self._lock:
            categories = {}
            for article in self._top_news:
                category = article.get("category", "Others")
                categories.setdefault(category, []).append(article)
            return categories

    def get_stats(self) -> dict:
        with self._lock:
            if not self._top_news:
                return {
                    "total_articles": 0,
                    "oldest_score": 0.0,
                    "newest_score": 0.0,
                    "by_category": {},
                }

            by_category = {}
            for article in self._top_news:
                category = article.get("category", "Others")
                by_category[category] = by_category.get(category, 0) + 1

            return {
                "total_articles": len(self._top_news),
                "candidate_pool": len(self._article_index),
                "oldest_score": self._top_news[-1].get("score", 0),
                "newest_score": self._top_news[0].get("score", 0),
                "by_category": by_category,
                "last_updated": self._top_news[0].get("ranked_at", "") if self._top_news else "",
                "ranking_weights": self.ranking_weights,
                "semantic": {
                    "mode": "synchronous_realtime",
                    "model": self.semantic_config.get("model_name", "sentence-transformers/all-MiniLM-L6-v2"),
                    "dedup_top_n": self._dedup_top_n,
                },
            }


_top_news_manager = None


def get_top_news_manager(
    data_dir: str = "DATA",
    source_weights: dict | None = None,
    ranking_weights: dict | None = None,
    semantic_config: dict | None = None,
) -> TopNewManager:
    global _top_news_manager
    if _top_news_manager is None:
        _top_news_manager = TopNewManager(
            data_dir,
            source_weights=source_weights,
            ranking_weights=ranking_weights,
            semantic_config=semantic_config,
        )
    return _top_news_manager
