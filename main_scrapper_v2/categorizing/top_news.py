"""
Top news management with fast basic ranking + async semantic scoring.

Pipeline:
  Scraper -> Basic ranking -> Priority semantic queue -> Semantic worker -> Score update
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime
from typing import Optional

from utils.time_utils import IST, now_ist
from categorizing.config import (
    DEFAULT_RANKING_WEIGHTS,
    DEFAULT_SEMANTIC_CONFIG,
    DEFAULT_SOURCE_WEIGHTS,
    TOP_NEWS_BOOST_KEYWORDS,
)
from categorizing.semantic_scoring import AsyncSemanticWorker, MiniLMEmbedder, SemanticScorer


class TopNewManager:
    """Thread-safe top-news manager with asynchronous semantic enrichment."""

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
        self.ranking_weights = {**DEFAULT_RANKING_WEIGHTS, **(ranking_weights or {})}
        self.semantic_config = {**DEFAULT_SEMANTIC_CONFIG, **(semantic_config or {})}

        self._lock = threading.Lock()
        self._top_news: list[dict] = []
        self._article_index: dict[str, dict] = {}

        self._top_news_dir = os.path.join(data_dir, "top_news")
        self._top_news_file = os.path.join(self._top_news_dir, "top_news.json")
        self._candidate_limit = int(self.semantic_config.get("candidate_limit", 2500))

        os.makedirs(self._top_news_dir, exist_ok=True)
        self._max_source_weight = max(1.0, max(self.source_weights.values(), default=1.0))

        self._semantic_worker: Optional[AsyncSemanticWorker] = None
        if self.semantic_config.get("enabled", True):
            self._start_semantic_pipeline()

        self._load_top_news()

    def shutdown(self) -> None:
        """Gracefully stop semantic worker threads."""
        if self._semantic_worker:
            self._semantic_worker.stop(timeout=2.0)
            self._semantic_worker = None

    def _start_semantic_pipeline(self) -> None:
        """Initialize async semantic worker with CPU model and micro-batching."""

        def scorer_factory() -> SemanticScorer:
            embedder = MiniLMEmbedder(
                model_name=self.semantic_config.get("model_name", "sentence-transformers/all-MiniLM-L6-v2"),
                max_length=int(self.semantic_config.get("max_length", 96)),
            )
            return SemanticScorer(
                embedder=embedder,
                cache_size=int(self.semantic_config.get("cache_size", 20000)),
                enable_heuristics=bool(self.semantic_config.get("heuristic_boost", True)),
                use_faiss_if_available=bool(self.semantic_config.get("use_faiss_if_available", True)),
            )

        self._semantic_worker = AsyncSemanticWorker(
            scorer_factory=scorer_factory,
            on_results=self._apply_semantic_results,
            queue_maxsize=int(self.semantic_config.get("queue_maxsize", 20000)),
            batch_size=int(self.semantic_config.get("batch_size", 32)),
            batch_timeout_ms=int(self.semantic_config.get("batch_timeout_ms", 25)),
            worker_threads=int(self.semantic_config.get("worker_threads", 1)),
            logger=self.logger,
        )
        self._semantic_worker.start()

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

    def _save_top_news(self) -> None:
        data = {
            "articles": self._top_news,
            "last_updated": now_ist().isoformat(),
            "algorithm_version": "2.0",
            "ranking_weights": self.ranking_weights,
            "semantic_enabled": self._semantic_worker is not None,
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

    def _parse_article_datetime(self, article: dict) -> Optional[datetime]:
        try:
            date_str = article.get("news_date", "")
            time_str = article.get("news_time", "")

            if not date_str or not time_str:
                return None

            parsed_time = time_str.replace(" IST", "").strip()
            dt_str = f"{date_str} {parsed_time}"
            dt = datetime.strptime(dt_str, "%Y-%m-%d %I:%M %p")
            return dt.replace(tzinfo=IST)
        except Exception:
            return None

    def _calculate_time_score(self, article: dict) -> float:
        article_dt = self._parse_article_datetime(article)
        if not article_dt:
            return 0.5

        age_seconds = (now_ist() - article_dt).total_seconds()
        if age_seconds < 0:
            return 1.0

        age_days = age_seconds / (24 * 3600)
        decay_days = 7
        return max(0.0, min(1.0, 2.718 ** (-age_days / decay_days)))

    def _calculate_keyword_boost(self, article: dict) -> float:
        title = article.get("news_caption", "").lower()
        summary = article.get("news_summary", "").lower()

        boost = 0.0
        for keyword, weight in TOP_NEWS_BOOST_KEYWORDS.items():
            if keyword in title:
                boost += weight * 1.5
            elif keyword in summary:
                boost += weight

        return min(1.2, boost)

    def _calculate_keyword_score(self, article: dict) -> float:
        """Normalize keyword boost to [0, 1] for weighted linear fusion."""
        return min(1.0, self._calculate_keyword_boost(article) / 1.2)

    def _get_source_weight(self, article: dict) -> float:
        source = article.get("source", "").lower()
        return self.source_weights.get(source, 1.0)

    def _calculate_source_score(self, article: dict) -> float:
        return min(1.0, self._get_source_weight(article) / self._max_source_weight)

    def _combine_scores(
        self,
        keyword_score: float,
        recency_score: float,
        source_score: float,
        semantic_score: float,
    ) -> float:
        w = self.ranking_weights
        return (
            w["keyword"] * keyword_score
            + w["recency"] * recency_score
            + w["source"] * source_score
            + w["semantic"] * semantic_score
        )

    def calculate_relevance_score(self, article: dict) -> float:
        keyword_score = self._calculate_keyword_score(article)
        recency_score = self._calculate_time_score(article)
        source_score = self._calculate_source_score(article)
        semantic_score = float(article.get("semantic_score", 0.0) or 0.0)
        return self._combine_scores(keyword_score, recency_score, source_score, semantic_score)

    def _get_article_id(self, article: dict) -> str:
        import hashlib

        source = article.get("source", "unknown")
        url = article.get("news_url", "")
        return hashlib.sha256(f"{source}:{url}".encode()).hexdigest()

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

    def _recompute_top_news_locked(self) -> None:
        scored_articles = []
        for article_id, article in self._article_index.items():
            keyword_score = self._calculate_keyword_score(article)
            recency_score = self._calculate_time_score(article)
            source_score = self._calculate_source_score(article)
            semantic_score = float(article.get("semantic_score", 0.0) or 0.0)
            final_score = self._combine_scores(keyword_score, recency_score, source_score, semantic_score)

            enriched = dict(article)
            enriched["id"] = article_id
            enriched["title"] = article.get("news_caption", "")[:100]
            enriched["source"] = article.get("source", "")
            enriched["category"] = article.get("category", "Others")
            enriched["score"] = final_score
            enriched["keyword_score"] = keyword_score
            enriched["recency_score"] = recency_score
            enriched["source_score"] = source_score
            enriched["semantic_score"] = semantic_score
            enriched["ranked_at"] = now_ist().isoformat()
            scored_articles.append(enriched)

        scored_articles.sort(key=lambda item: item["score"], reverse=True)
        self._top_news = scored_articles[:100]

    def _semantic_priority(self, article: dict) -> float:
        """Lower value means higher queue priority."""
        keyword_score = self._calculate_keyword_score(article)
        recency_score = self._calculate_time_score(article)
        source_score = self._calculate_source_score(article)

        # High-impact items should be processed first in semantic queue.
        return -(0.45 * keyword_score + 0.4 * recency_score + 0.15 * source_score)

    def _enqueue_semantic_tasks(self, updated_article_ids: list[str]) -> None:
        if not self._semantic_worker:
            return

        enqueued = 0
        dropped = 0

        for article_id in updated_article_ids:
            article = self._article_index.get(article_id)
            if not article:
                continue

            title = article.get("news_caption", "")
            summary = article.get("news_summary", "")
            text = SemanticScorer.build_text(title, summary)
            text_hash = SemanticScorer.text_hash(text)

            # Skip when semantic score already computed for unchanged text.
            if article.get("semantic_text_hash") == text_hash and article.get("semantic_score") is not None:
                continue

            accepted = self._semantic_worker.submit(
                article_id=article_id,
                title=title,
                summary=summary,
                priority=self._semantic_priority(article),
                text_hash=text_hash,
            )
            if accepted:
                enqueued += 1
            else:
                dropped += 1

        if dropped and self.logger:
            self.logger.warning(f"Semantic queue full: dropped {dropped} items")

        if enqueued and self.logger:
            self.logger.debug(f"Semantic tasks queued: {enqueued}")

    def _apply_semantic_results(self, results: list) -> None:
        if not results:
            return

        with self._lock:
            changed = 0
            queue_wait_samples = []

            for result in results:
                article = self._article_index.get(result.article_id)
                if not article:
                    continue

                title = article.get("news_caption", "")
                summary = article.get("news_summary", "")
                text = SemanticScorer.build_text(title, summary)

                article["semantic_score"] = float(result.semantic_score)
                article["semantic_anchor"] = result.semantic_anchor
                article["semantic_text_hash"] = SemanticScorer.text_hash(text)
                article["semantic_scored_at"] = now_ist().isoformat()
                changed += 1
                queue_wait_samples.append(result.queue_wait_ms)

            if not changed:
                return

            self._recompute_top_news_locked()
            self._save_top_news()

            if self.logger and queue_wait_samples:
                avg_wait = sum(queue_wait_samples) / len(queue_wait_samples)
                self.logger.debug(
                    f"Semantic updates applied: {changed}, avg queue wait={avg_wait:.1f}ms"
                )

    def update_top_news(self, articles: list[dict]) -> list[dict]:
        if not articles:
            return self._top_news

        updated_ids: list[str] = []

        with self._lock:
            for article in articles:
                article_id = self._get_article_id(article)
                existing = self._article_index.get(article_id, {})
                merged = {**existing, **article}
                self._article_index[article_id] = merged
                updated_ids.append(article_id)

            self._trim_article_index_locked()
            self._recompute_top_news_locked()
            self._save_top_news()

        # Queue semantic scoring after fast basic ranking is already persisted.
        self._enqueue_semantic_tasks(updated_ids)

        if self._top_news:
            self.logger.info(
                f"Updated top news: {len(self._top_news)} articles, min score={self._top_news[-1]['score']:.2f}"
            )

        return self._top_news

    def get_top_news(self, limit: int = 100, category: Optional[str] = None) -> list[dict]:
        with self._lock:
            articles = self._top_news[:limit]
            if category:
                articles = [item for item in articles if item.get("category", "Others") == category]
            return articles

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

            semantic_stats = self._semantic_worker.stats() if self._semantic_worker else {}

            return {
                "total_articles": len(self._top_news),
                "candidate_pool": len(self._article_index),
                "oldest_score": self._top_news[-1].get("score", 0),
                "newest_score": self._top_news[0].get("score", 0),
                "by_category": by_category,
                "last_updated": self._top_news[0].get("ranked_at", "") if self._top_news else "",
                "ranking_weights": self.ranking_weights,
                "semantic": semantic_stats,
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
