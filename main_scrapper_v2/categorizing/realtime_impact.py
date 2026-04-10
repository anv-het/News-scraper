"""
Real-time finance impact scoring for incoming news items.

Design goals:
- CPU-only, low-latency scoring per item
- No external API calls during scoring
- Preloaded NLP models and compiled rule patterns
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

from categorizing.config import (
    DEFAULT_RANKING_WEIGHTS,
    ENTITY_ROLE_PATTERNS,
    EVENT_PATTERNS,
    EVENT_WEIGHTS,
    TOP_NEWS_BOOST_KEYWORDS,
)
from utils.time_utils import IST, now_ist

try:
    import spacy
except Exception:  # pragma: no cover - optional dependency runtime fallback
    spacy = None


@dataclass
class ImpactBreakdown:
    semantic_score: float
    keyword_score: float
    entity_score: float
    event_score: float
    recency_score: float
    source_score: float
    final_score: float
    semantic_anchor: str
    entities_org: list[str]
    entities_person: list[str]
    entities_gpe: list[str]
    events: list[str]


class _EmbeddingCache:
    """Thread-safe LRU cache for text embeddings."""

    def __init__(self, max_size: int = 20000):
        self.max_size = max(1000, int(max_size))
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, torch.Tensor] = OrderedDict()

    def get(self, key: str) -> Optional[torch.Tensor]:
        with self._lock:
            value = self._cache.get(key)
            if value is None:
                return None
            self._cache.move_to_end(key)
            return value

    def set(self, key: str, value: torch.Tensor) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)


class _MiniLMEncoder:
    """Compact embedding encoder loaded once into memory."""

    def __init__(
        self,
        model_name: str,
        max_length: int = 96,
        fallback_model_name: str | None = None,
        logger=None,
    ):
        self.model_name = model_name
        self.fallback_model_name = fallback_model_name
        self.max_length = max(32, int(max_length))
        self.logger = logger
        self._tokenizer = None
        self._model = None
        self._load_lock = threading.Lock()

    def _load_model(self, model_name: str) -> None:
        self._tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)
        self._model = AutoModel.from_pretrained(model_name)
        self._model.eval()
        self._model.to("cpu")
        self.model_name = model_name

    def _ensure_model(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        with self._load_lock:
            if self._model is not None and self._tokenizer is not None:
                return

            try:
                self._load_model(self.model_name)
            except Exception as exc:
                if not self.fallback_model_name:
                    raise

                if self.logger:
                    self.logger.warning(
                        "Primary semantic model '%s' unavailable (%s). Falling back to '%s'.",
                        self.model_name,
                        exc,
                        self.fallback_model_name,
                    )
                self._load_model(self.fallback_model_name)

    def encode_batch(self, texts: list[str]) -> torch.Tensor:
        self._ensure_model()
        if not texts:
            return torch.empty((0, 384), dtype=torch.float32)

        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        )

        with torch.inference_mode():
            outputs = self._model(**encoded)
            token_embeddings = outputs.last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()
            pooled = torch.sum(token_embeddings * mask, dim=1) / torch.clamp(mask.sum(dim=1), min=1e-9)
            return F.normalize(pooled, p=2, dim=1).cpu()


class FinanceSemanticScorer:
    """Semantic similarity scoring against finance concept vectors."""

    def __init__(
        self,
        model_name: str,
        max_length: int,
        cache_size: int,
        fallback_model_name: str | None = None,
        enable_heuristics: bool = True,
        logger=None,
    ):
        self._encoder = _MiniLMEncoder(
            model_name=model_name,
            max_length=max_length,
            fallback_model_name=fallback_model_name,
            logger=logger,
        )
        self._cache = _EmbeddingCache(max_size=cache_size)
        self.enable_heuristics = bool(enable_heuristics)
        self._keyword_pairs = list(TOP_NEWS_BOOST_KEYWORDS.items())
        strongest = sorted((float(weight) for _, weight in self._keyword_pairs), reverse=True)[:8]
        self._keyword_norm = max(1.0, sum(strongest))

        self._concept_texts, self._concept_weights = self._build_concepts()
        self._concept_matrix = self._encoder.encode_batch(self._concept_texts)
        self._weight_tensor = torch.tensor(self._concept_weights, dtype=torch.float32)

        self._impact_regex = re.compile(
            r"\b(earnings|guidance|revenue|profit|inflation|cpi|ppi|rate\s+hike|rate\s+cut|"
            r"ceo|merger|acquisition|sanctions|war|default|bankruptcy)\b",
            re.IGNORECASE,
        )

    def _build_concepts(self) -> tuple[list[str], list[float]]:
        concepts: list[str] = []
        weights: list[float] = []

        for keyword, weight in TOP_NEWS_BOOST_KEYWORDS.items():
            concepts.append(f"Market impact signal related to {keyword}.")
            weights.append(float(weight))

        for event_name, event_weight in EVENT_WEIGHTS.items():
            event_text = event_name.replace("_", " ")
            concepts.append(f"Breaking finance event about {event_text} affecting markets.")
            weights.append(float(event_weight) * 0.85)

        max_weight = max(weights, default=1.0)
        norm_weights = [min(1.0, max(0.05, w / max_weight)) for w in weights]
        return concepts, norm_weights

    @staticmethod
    def _text_hash(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()

    def _embedding_for_text(self, text: str) -> torch.Tensor:
        key = self._text_hash(text)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        embedding = self._encoder.encode_batch([text])[0]
        self._cache.set(key, embedding)
        return embedding

    def _keyword_lexical_score(self, text: str) -> float:
        lowered = text.lower()
        lexical = 0.0
        for keyword, weight in self._keyword_pairs:
            if keyword in lowered:
                lexical += float(weight)
        return min(1.0, max(0.0, lexical / self._keyword_norm))

    def score(self, text: str) -> tuple[float, str, float]:
        clean_text = (text or "").strip()
        if not clean_text:
            return 0.0, "", 0.0

        emb = self._embedding_for_text(clean_text)
        sims = torch.mv(self._concept_matrix, emb)

        k = min(6, sims.shape[0])
        top_vals, top_idx = torch.topk(sims, k=k)
        top_positive = torch.clamp(top_vals, min=0.0)

        chosen_weights = self._weight_tensor[top_idx]
        weighted_mean = float(
            (top_positive * chosen_weights).sum().item() / max(chosen_weights.sum().item(), 1e-6)
        )
        max_sim = float(top_positive[0].item())
        keyword_score = self._keyword_lexical_score(clean_text)

        heuristic = 0.05 if (self.enable_heuristics and self._impact_regex.search(clean_text)) else 0.0
        score = min(1.0, max(0.0, 0.52 * max_sim + 0.26 * weighted_mean + 0.18 * keyword_score + heuristic))

        best_anchor = self._concept_texts[int(top_idx[0].item())]
        return score, best_anchor, keyword_score


class FastEntityExtractor:
    """Fast ORG/PERSON/GPE extraction with spaCy and heuristic fallback."""

    def __init__(self, spacy_enabled: bool = True, spacy_model: str = "en_core_web_sm"):
        self._nlp = None
        if spacy_enabled and spacy is not None:
            try:
                self._nlp = spacy.load(
                    spacy_model,
                    disable=["tagger", "parser", "attribute_ruler", "lemmatizer", "textcat"],
                )
            except Exception:
                self._nlp = None

        self._org_suffix_regex = re.compile(
            r"\b([A-Z][A-Za-z&.\-]+(?:\s+[A-Z][A-Za-z&.\-]+){0,3}\s+"
            r"(?:Inc|Corp|Corporation|Ltd|Limited|PLC|Bank|Group|Holdings|Technologies|Tech))\b"
        )
        self._person_regex = re.compile(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b")

        gpe_list = [
            "US", "USA", "United States", "India", "China", "Russia", "Ukraine", "Japan",
            "Germany", "France", "UK", "Britain", "Europe", "Middle East", "Asia", "Delhi",
            "Mumbai", "Bengaluru", "London", "New York", "Washington", "Beijing", "Moscow",
        ]
        self._gpe_regex = re.compile(r"\b(" + "|".join(re.escape(x) for x in gpe_list) + r")\b")

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip(" \t\n\r.,;:!-"))

    def _extract_heuristic(self, text: str) -> tuple[list[str], list[str], list[str]]:
        orgs = {self._clean(m.group(1)) for m in self._org_suffix_regex.finditer(text)}
        persons = {self._clean(m.group(1)) for m in self._person_regex.finditer(text)}
        gpes = {self._clean(m.group(1)) for m in self._gpe_regex.finditer(text)}

        persons = {p for p in persons if p not in orgs}
        return sorted(orgs), sorted(persons), sorted(gpes)

    def extract(self, text: str) -> tuple[list[str], list[str], list[str]]:
        clean_text = (text or "").strip()
        if not clean_text:
            return [], [], []

        if self._nlp is None:
            return self._extract_heuristic(clean_text)

        doc = self._nlp(clean_text)
        orgs: set[str] = set()
        persons: set[str] = set()
        gpes: set[str] = set()

        for ent in doc.ents:
            label = ent.label_
            val = self._clean(ent.text)
            if not val:
                continue
            if label == "ORG":
                orgs.add(val)
            elif label == "PERSON":
                persons.add(val)
            elif label == "GPE":
                gpes.add(val)

        # Heuristic fallback can add missing entities even when spaCy misses them.
        h_orgs, h_persons, h_gpes = self._extract_heuristic(clean_text)
        orgs.update(h_orgs)
        persons.update(h_persons)
        gpes.update(h_gpes)

        persons = {p for p in persons if p not in orgs}
        return sorted(orgs), sorted(persons), sorted(gpes)


class EntityImpactScorer:
    """Entity weighting resolver for ORG/PERSON/GPE mentions."""

    def __init__(self):
        self._ceo_patterns = [re.compile(pat, re.IGNORECASE) for pat in ENTITY_ROLE_PATTERNS.get("ceo_founder", [])]
        self._cfo_board_patterns = [re.compile(pat, re.IGNORECASE) for pat in ENTITY_ROLE_PATTERNS.get("cfo_board", [])]
        self._macro_context_regex = re.compile(
            r"\b(inflation|gdp|recession|election|sanction|war|policy|central\s+bank|interest\s+rate)\b",
            re.IGNORECASE,
        )

    def score(
        self,
        orgs: list[str],
        persons: list[str],
        gpes: list[str],
        context_text: str,
    ) -> float:
        score = 0.0

        # ORG weights: +0.5 per mention
        score += 0.5 * len(orgs)

        # PERSON role weights
        ceo_hit = any(pattern.search(context_text) for pattern in self._ceo_patterns)
        cfo_board_hit = any(pattern.search(context_text) for pattern in self._cfo_board_patterns)

        for _ in persons:
            if ceo_hit:
                score += 0.7
            elif cfo_board_hit:
                score += 0.4
            else:
                score += 0.1

        # GPE contributes only in macro/geopolitical context.
        if gpes and self._macro_context_regex.search(context_text):
            score += min(0.2, 0.05 * len(gpes))

        return min(1.0, max(0.0, score))


class RuleEventDetector:
    """Rule-based high-impact event detector."""

    def __init__(self):
        self._compiled: dict[str, list[re.Pattern]] = {
            name: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for name, patterns in EVENT_PATTERNS.items()
        }

    def detect(self, text: str) -> tuple[float, list[str]]:
        clean_text = (text or "").strip()
        if not clean_text:
            return 0.0, []

        score = 0.0
        matched: list[str] = []

        for event_name, patterns in self._compiled.items():
            if any(regex.search(clean_text) for regex in patterns):
                matched.append(event_name)
                weight = float(EVENT_WEIGHTS.get(event_name, 0.6))
                score += (1.0 - score) * weight

        return min(1.0, max(0.0, score)), matched


class RealTimeImpactScorer:
    """Synchronous impact scorer optimized for per-item latency."""

    def __init__(
        self,
        source_weights: dict,
        ranking_weights: Optional[dict] = None,
        runtime_config: Optional[dict] = None,
        logger=None,
    ):
        self.logger = logger
        self.source_weights = source_weights or {}
        self.runtime_config = runtime_config or {}
        self.max_source_weight = max(1.0, max(self.source_weights.values(), default=1.0))

        merged_weights = {**DEFAULT_RANKING_WEIGHTS, **(ranking_weights or {})}
        self.ranking_weights = self._normalize_weights(merged_weights)

        self.semantic_text_chars = max(120, int(self.runtime_config.get("semantic_text_chars", 420)))
        self.ner_text_chars = max(80, int(self.runtime_config.get("ner_text_chars", 240)))
        self.recency_decay_hours = max(2, int(self.runtime_config.get("recency_decay_hours", 18)))

        self.semantic = FinanceSemanticScorer(
            model_name=self.runtime_config.get("model_name", "ProsusAI/finbert"),
            max_length=int(self.runtime_config.get("max_length", 96)),
            cache_size=int(self.runtime_config.get("cache_size", 20000)),
            fallback_model_name=self.runtime_config.get(
                "fallback_model_name",
                "sentence-transformers/all-MiniLM-L6-v2",
            ),
            enable_heuristics=bool(self.runtime_config.get("heuristic_boost", True)),
            logger=self.logger,
        )
        self.ner = FastEntityExtractor(
            spacy_enabled=bool(self.runtime_config.get("spacy_enabled", True)),
            spacy_model=self.runtime_config.get("spacy_model", "en_core_web_sm"),
        )
        self.entity_resolver = EntityImpactScorer()
        self.event_detector = RuleEventDetector()

    @staticmethod
    def _normalize_weights(weights: dict) -> dict:
        # Backward compatibility for older key names.
        if "keyword" in weights and "semantic" not in weights:
            weights["semantic"] = float(weights["keyword"])
            weights["keyword"] = 0.0

        expected = ["semantic", "keyword", "entity", "event", "recency", "source"]
        filtered = {k: max(0.0, float(weights.get(k, 0.0))) for k in expected}
        total = sum(filtered.values())
        if total <= 0:
            filtered = dict(DEFAULT_RANKING_WEIGHTS)
            total = sum(filtered.values())
        return {k: v / total for k, v in filtered.items()}

    @staticmethod
    def _title(article: dict) -> str:
        return (article.get("news_caption") or article.get("title") or "").strip()

    @staticmethod
    def _content(article: dict) -> str:
        return (article.get("news_summary") or article.get("content") or "").strip()

    @staticmethod
    def _parse_datetime(article: dict) -> Optional[datetime]:
        timestamp = article.get("timestamp")
        if timestamp:
            try:
                if isinstance(timestamp, (int, float)):
                    return datetime.fromtimestamp(float(timestamp), tz=IST)
                if isinstance(timestamp, str):
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)
            except Exception:
                pass

        date_str = (article.get("news_date") or "").strip()
        time_str = (article.get("news_time") or "").replace(" IST", "").strip()
        if not date_str or not time_str:
            return None

        formats = [
            "%Y-%m-%d %I:%M %p",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %I:%M:%S %p",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(f"{date_str} {time_str}", fmt).replace(tzinfo=IST)
            except Exception:
                continue
        return None

    def calculate_recency_score(self, article: dict) -> float:
        article_dt = self._parse_datetime(article)
        if article_dt is None:
            return 0.45

        age_seconds = (now_ist() - article_dt).total_seconds()
        if age_seconds <= 0:
            return 1.0

        age_hours = age_seconds / 3600.0
        return min(1.0, max(0.0, math.exp(-age_hours / float(self.recency_decay_hours))))

    def calculate_source_score(self, article: dict) -> float:
        source = (article.get("source") or "").lower().strip()
        return min(1.0, max(0.0, self.source_weights.get(source, 1.0) / self.max_source_weight))

    def combine_scores(
        self,
        semantic_score: float,
        keyword_score: float,
        entity_score: float,
        event_score: float,
        recency_score: float,
        source_score: float,
    ) -> float:
        w = self.ranking_weights
        return (
            w["semantic"] * semantic_score
            + w["keyword"] * keyword_score
            + w["entity"] * entity_score
            + w["event"] * event_score
            + w["recency"] * recency_score
            + w["source"] * source_score
        )

    def score_item(self, article: dict) -> ImpactBreakdown:
        title = self._title(article)
        content = self._content(article)
        merged = f"{title}. {content}".strip(" .")

        semantic_text = merged[: self.semantic_text_chars]
        ner_text = merged[: self.ner_text_chars]

        semantic_score, semantic_anchor, keyword_score = self.semantic.score(semantic_text)

        orgs, persons, gpes = self.ner.extract(ner_text)
        context_lower = merged.lower()
        entity_score = self.entity_resolver.score(orgs, persons, gpes, context_lower)

        event_score, matched_events = self.event_detector.detect(merged)
        recency_score = self.calculate_recency_score(article)
        source_score = self.calculate_source_score(article)

        final_score = self.combine_scores(
            semantic_score=semantic_score,
            keyword_score=keyword_score,
            entity_score=entity_score,
            event_score=event_score,
            recency_score=recency_score,
            source_score=source_score,
        )

        return ImpactBreakdown(
            semantic_score=float(semantic_score),
            keyword_score=float(keyword_score),
            entity_score=float(entity_score),
            event_score=float(event_score),
            recency_score=float(recency_score),
            source_score=float(source_score),
            final_score=float(final_score),
            semantic_anchor=semantic_anchor,
            entities_org=orgs,
            entities_person=persons,
            entities_gpe=gpes,
            events=matched_events,
        )
