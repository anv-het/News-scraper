"""
MongoDB storage adapter for normalized news documents.

Writes are optional and controlled through .env settings.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

try:
    from pymongo import MongoClient, UpdateOne
    from pymongo.errors import PyMongoError
except Exception:  # pragma: no cover - handled via availability checks
    MongoClient = None
    UpdateOne = None

    class PyMongoError(Exception):
        """Fallback error type when pymongo is unavailable."""


class MongoStorage:
    """Thread-safe MongoDB writer for scored news items."""

    URL_UNIQUE_INDEX_NAME = "uniq_news_source_url"
    # Some MongoDB-compatible engines reject $ne in partial indexes.
    # Use a supported equivalent for non-empty strings.
    URL_UNIQUE_PARTIAL_FILTER = {"news_url": {"$type": "string", "$gt": ""}}

    def __init__(
        self,
        enabled: bool = False,
        mongo_url: str = "mongodb://localhost:27017",
        database_name: str = "news_scrapper",
        collection_name: str = "news",
        top_news_enabled: bool = False,
        top_news_collection_name: str = "top_news_history",
        logger=None,
    ):
        self.enabled = bool(enabled)
        self.mongo_url = mongo_url
        self.database_name = database_name
        self.collection_name = collection_name
        self.top_news_enabled = bool(top_news_enabled)
        self.top_news_collection_name = top_news_collection_name
        self.logger = logger or logging.getLogger("scrapper")

        self.available = False
        self._lock = threading.Lock()
        self._client = None
        self._collection = None
        self._top_news_collection = None

        if not self.enabled:
            self.logger.info("MongoDB storage disabled")
            return

        if MongoClient is None:
            self.logger.error("MongoDB enabled but pymongo is not installed")
            return

        try:
            self._client = MongoClient(self.mongo_url, serverSelectionTimeoutMS=5000)
            self._client.admin.command("ping")
            self._collection = self._client[self.database_name][self.collection_name]
            
            if self.top_news_enabled:
                self._top_news_collection = self._client[self.database_name][self.top_news_collection_name]

            self._ensure_indexes()

            self.available = True
            self.logger.info(
                f"MongoDB storage enabled ({self.database_name}.{self.collection_name})"
            )
        except Exception as exc:
            self.logger.error(f"MongoDB init failed: {exc}")
            self.available = False

    def _ensure_indexes(self):
        """Create indexes and migrate legacy URL uniqueness index if needed."""
        existing = self._collection.index_information().get(self.URL_UNIQUE_INDEX_NAME)
        should_recreate = True

        if existing:
            same_key = existing.get("key") == [("news_source", 1), ("news_url", 1)]
            is_unique = bool(existing.get("unique"))
            same_partial = (
                existing.get("partialFilterExpression") == self.URL_UNIQUE_PARTIAL_FILTER
            )

            if same_key and is_unique and same_partial:
                should_recreate = False
            else:
                self.logger.warning(
                    "Rebuilding Mongo index uniq_news_source_url to ignore empty news_url"
                )
                self._collection.drop_index(self.URL_UNIQUE_INDEX_NAME)

        if should_recreate:
            self._collection.create_index(
                [("news_source", 1), ("news_url", 1)],
                unique=True,
                name=self.URL_UNIQUE_INDEX_NAME,
                partialFilterExpression=self.URL_UNIQUE_PARTIAL_FILTER,
            )

        self._collection.create_index(
            [("news_date", -1), ("news_time", -1)],
            name="news_date_time_desc",
        )
        
        if self._top_news_collection is not None:
            self._top_news_collection.create_index(
                [("news_source", 1), ("news_url", 1)],
                unique=True,
                name=self.URL_UNIQUE_INDEX_NAME,
                partialFilterExpression=self.URL_UNIQUE_PARTIAL_FILTER,
            )
            self._top_news_collection.create_index(
                [("top_score", -1)],
                name="top_score_desc",
            )

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_categories(article: dict, main_category: str) -> list[str]:
        categories = article.get("categories")
        if isinstance(categories, list):
            cleaned = [str(item).strip().lower() for item in categories if str(item).strip()]
            if cleaned:
                return cleaned
        return [main_category]

    @staticmethod
    def _normalize_main_category(article: dict) -> str:
        candidate = (
            article.get("main_category")
            or article.get("category")
            or (article.get("categories") or ["others"])[0]
            or "others"
        )
        return str(candidate).strip().lower() or "others"

    def _build_document(self, source: str, article: dict) -> dict:
        main_category = self._normalize_main_category(article)
        categories = self._normalize_categories(article, main_category)

        return {
            "unique_id": str(article.get("unique_id") or "").strip(),
            "news_source": str(article.get("news_source") or article.get("source") or source or "").strip().lower(),
            "news_date": str(article.get("news_date") or "").strip(),
            "news_time": str(article.get("news_time") or "").strip(),
            "scraped_at": str(article.get("scraped_at") or "").strip(),
            "news_caption": str(article.get("news_caption") or "").strip(),
            "news_summary": str(article.get("news_summary") or "").strip(),
            "news_url": str(article.get("news_url") or "").strip(),
            "image_url": str(article.get("image_url") or "").strip(),
            "main_category": main_category,
            "categories": categories,
            "top_score": self._as_float(article.get("top_score", article.get("score", 0.0))),
            "top_news": bool(article.get("top_news", False)),
        }

    @staticmethod
    def _identity_filter(document: dict) -> dict:
        source = document.get("news_source", "")
        news_url = document.get("news_url", "")
        if news_url:
            return {"news_source": source, "news_url": news_url}

        return {
            "news_source": source,
            "news_date": document.get("news_date", ""),
            "news_time": document.get("news_time", ""),
            "news_caption": document.get("news_caption", ""),
        }

    def save_news(self, source: str, news_list: list[dict]) -> int:
        """Upsert scored news items into MongoDB and return changed count."""
        if not self.available or not news_list:
            return 0

        operations = []
        for item in news_list:
            if not isinstance(item, dict):
                continue
            doc = self._build_document(source, item)
            
            # Extract top_news flag to prevent $set from overwriting an existing True flag
            # We use $setOnInsert so new documents default to False (or whatever is passed)
            top_news_val = doc.pop("top_news", False)
            
            operations.append(
                UpdateOne(
                    self._identity_filter(doc),
                    {
                        "$set": doc,
                        "$setOnInsert": {"top_news": top_news_val}
                    },
                    upsert=True,
                )
            )

        if not operations:
            return 0

        with self._lock:
            try:
                result = self._collection.bulk_write(operations, ordered=False)
                return int(result.upserted_count + result.modified_count)
            except PyMongoError as exc:
                self.logger.error(f"MongoDB write failed: {exc}")
                return 0

    def mark_as_top_news(self, articles: list[dict]) -> int:
        """Mark specific articles as having entered top news (historical flag)."""
        if not self.available or not articles:
            return 0
            
        operations = []
        for item in articles:
            if not isinstance(item, dict):
                continue
                
            unique_id = str(item.get("unique_id", "")).strip()
            # If the article has a unique_id field mapped in MongoDB, match by it.
            # Otherwise use the identity filter mapping.
            if unique_id:
                filter_query = {"unique_id": unique_id}
            else:
                doc = self._build_document("", item)
                filter_query = self._identity_filter(doc)
                
            operations.append(
                UpdateOne(
                    filter_query,
                    {"$set": {"top_news": True}},
                    upsert=False, # We don't upsert here; save_news should have already saved it
                )
            )
            
        if not operations:
            return 0
            
        with self._lock:
            try:
                result = self._collection.bulk_write(operations, ordered=False)
                modified = int(result.modified_count)
            except PyMongoError as exc:
                self.logger.error(f"MongoDB mark_as_top_news failed: {exc}")
                return 0
                
            if self.top_news_enabled and self._top_news_collection is not None:
                tn_operations = []
                for item in articles:
                    if not isinstance(item, dict):
                        continue
                    doc = self._build_document("", item)
                    # Force the flag to True for the dedicated collection
                    doc["top_news"] = True
                    tn_operations.append(
                        UpdateOne(
                            self._identity_filter(doc),
                            {"$set": doc},
                            upsert=True,
                        )
                    )
                if tn_operations:
                    try:
                        self._top_news_collection.bulk_write(tn_operations, ordered=False)
                    except PyMongoError as exc:
                        self.logger.error(f"MongoDB top news dedicated collection write failed: {exc}")
                        
            return modified
