"""
Asynchronous semantic scoring pipeline for market-impact relevance.

Design goals:
- CPU-first inference with a compact MiniLM encoder
- Non-blocking scoring via async worker queue
- Batch embedding for throughput and cache for duplicate headlines
- Priority scheduling so important items are scored first
"""

from __future__ import annotations

import hashlib
import queue
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Optional

import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer


DEFAULT_SEMANTIC_ANCHORS: list[tuple[str, str]] = [
    (
        "interest_rate_changes",
        "Central bank interest rate hike, rate cut, monetary policy or bond yield surprise.",
    ),
    (
        "earnings_results",
        "Company quarterly earnings, revenue, profit guidance beat or miss estimates.",
    ),
    (
        "mergers_acquisitions",
        "Merger, acquisition, strategic stake purchase, takeover bid, or consolidation deal.",
    ),
    (
        "geopolitical_events",
        "Geopolitical tension, sanctions, cross-border conflict, diplomatic crisis or military escalation.",
    ),
    (
        "commodity_price_changes",
        "Oil, gas, gold, metal, agricultural commodity price spike or sharp decline.",
    ),
    (
        "regulations_bans",
        "Government regulation, policy ban, legal restriction, compliance enforcement, or licensing change.",
    ),
    (
        "war_political_events",
        "War news, national election, international political shock, regime change, or parliament decision.",
    ),
]


@dataclass(order=True)
class SemanticTask:
    priority: float
    sequence: int
    article_id: str = field(compare=False)
    title: str = field(compare=False)
    summary: str = field(compare=False)
    text_hash: str = field(compare=False)
    enqueued_at: float = field(compare=False, default_factory=time.perf_counter)


@dataclass
class SemanticResult:
    article_id: str
    semantic_score: float
    semantic_anchor: str
    queue_wait_ms: float


class EmbeddingLRUCache:
    """Thread-safe LRU cache for normalized embedding tensors."""

    def __init__(self, max_size: int = 20000):
        self.max_size = max_size
        self._cache: OrderedDict[str, torch.Tensor] = OrderedDict()
        self._lock = threading.Lock()

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


class MiniLMEmbedder:
    """Compact sentence embedding backend using transformers on CPU."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        max_length: int = 96,
    ):
        self.model_name = model_name
        self.max_length = max_length
        self._tokenizer = None
        self._model = None
        self._load_lock = threading.Lock()

    def _ensure_model(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        with self._load_lock:
            if self._model is not None and self._tokenizer is not None:
                return

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModel.from_pretrained(self.model_name)
            self._model.eval()
            self._model.to("cpu")

    def encode_batch(self, texts: list[str]) -> torch.Tensor:
        """Return L2-normalized embeddings tensor with shape [N, D]."""
        if not texts:
            return torch.empty((0, 384), dtype=torch.float32)

        self._ensure_model()

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
            normalized = F.normalize(pooled, p=2, dim=1)

        return normalized.cpu()


class SemanticScorer:
    """Computes max cosine similarity against predefined market-impact anchors."""

    def __init__(
        self,
        embedder: Optional[MiniLMEmbedder] = None,
        anchors: Optional[list[tuple[str, str]]] = None,
        cache_size: int = 20000,
        enable_heuristics: bool = True,
        use_faiss_if_available: bool = True,
    ):
        self.embedder = embedder or MiniLMEmbedder()
        self.anchors = anchors or DEFAULT_SEMANTIC_ANCHORS
        self.cache = EmbeddingLRUCache(max_size=cache_size)
        self.enable_heuristics = enable_heuristics
        self.use_faiss_if_available = use_faiss_if_available

        self._anchors_lock = threading.Lock()
        self._anchor_matrix: Optional[torch.Tensor] = None
        self._anchor_names: list[str] = []
        self._faiss_index = None

    @staticmethod
    def build_text(title: str, summary: str) -> str:
        title = (title or "").strip()
        summary = (summary or "").strip()
        return f"{title}. {summary}".strip(" .")

    @staticmethod
    def text_hash(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()

    def _ensure_anchor_matrix(self) -> None:
        if self._anchor_matrix is not None:
            return

        with self._anchors_lock:
            if self._anchor_matrix is not None:
                return

            anchor_texts = [text for _, text in self.anchors]
            self._anchor_names = [name for name, _ in self.anchors]
            matrix = self.embedder.encode_batch(anchor_texts)
            self._anchor_matrix = matrix

            if self.use_faiss_if_available:
                try:
                    import faiss  # type: ignore

                    index = faiss.IndexFlatIP(matrix.shape[1])
                    index.add(matrix.numpy())
                    self._faiss_index = index
                except Exception:
                    self._faiss_index = None

    def _heuristic_boost(self, text: str, anchor: str) -> float:
        if not self.enable_heuristics:
            return 0.0

        lowered = text.lower()
        boost = 0.0

        if anchor == "earnings_results":
            if re.search(r"\b\d+(\.\d+)?%\b", lowered):
                boost += 0.03
            if "beat" in lowered and "estimate" in lowered:
                boost += 0.04
            if "miss" in lowered and "estimate" in lowered:
                boost += 0.04

        if anchor == "interest_rate_changes":
            if any(word in lowered for word in ["bps", "basis points", "rate hike", "rate cut"]):
                boost += 0.04

        return min(0.08, boost)

    def score_texts(self, texts: list[str]) -> list[tuple[float, str]]:
        """Return [(semantic_score, winning_anchor), ...] for each input text."""
        if not texts:
            return []

        self._ensure_anchor_matrix()

        embeddings: list[Optional[torch.Tensor]] = [None] * len(texts)
        missing_idx: list[int] = []
        missing_texts: list[str] = []

        for idx, text in enumerate(texts):
            key = self.text_hash(text)
            cached = self.cache.get(key)
            if cached is not None:
                embeddings[idx] = cached
            else:
                missing_idx.append(idx)
                missing_texts.append(text)

        if missing_texts:
            missing_embeddings = self.embedder.encode_batch(missing_texts)
            for idx, emb in zip(missing_idx, missing_embeddings):
                key = self.text_hash(texts[idx])
                emb_cpu = emb.detach().cpu()
                self.cache.set(key, emb_cpu)
                embeddings[idx] = emb_cpu

        item_matrix = torch.stack([emb for emb in embeddings if emb is not None])

        if self._faiss_index is not None:
            distances, indices = self._faiss_index.search(item_matrix.numpy(), 1)
            scores = distances[:, 0]
            anchors = [self._anchor_names[i] for i in indices[:, 0]]
        else:
            similarity = item_matrix @ self._anchor_matrix.T
            max_vals, max_idx = torch.max(similarity, dim=1)
            scores = max_vals.numpy()
            anchors = [self._anchor_names[i] for i in max_idx.tolist()]

        final: list[tuple[float, str]] = []
        for text, raw_score, anchor in zip(texts, scores, anchors):
            score = float(raw_score)
            score = min(1.0, max(0.0, score + self._heuristic_boost(text, anchor)))
            final.append((score, anchor))

        return final


class AsyncSemanticWorker:
    """Non-blocking semantic pipeline with priority queue and micro-batches."""

    def __init__(
        self,
        scorer_factory: Callable[[], SemanticScorer],
        on_results: Callable[[list[SemanticResult]], None],
        queue_maxsize: int = 20000,
        batch_size: int = 32,
        batch_timeout_ms: int = 25,
        worker_threads: int = 1,
        logger=None,
    ):
        self.scorer_factory = scorer_factory
        self.on_results = on_results
        self.batch_size = batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self.worker_threads = max(1, worker_threads)
        self.logger = logger

        self._queue: queue.PriorityQueue[SemanticTask] = queue.PriorityQueue(maxsize=queue_maxsize)
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._counter = 0
        self._counter_lock = threading.Lock()

        self.processed = 0
        self.dropped = 0

    def start(self) -> None:
        if self._threads:
            return

        for idx in range(self.worker_threads):
            scorer = self.scorer_factory()
            thread = threading.Thread(
                target=self._worker_loop,
                args=(scorer,),
                name=f"semantic-worker-{idx + 1}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def submit(self, article_id: str, title: str, summary: str, priority: float, text_hash: str) -> bool:
        with self._counter_lock:
            self._counter += 1
            sequence = self._counter

        task = SemanticTask(
            priority=priority,
            sequence=sequence,
            article_id=article_id,
            title=title,
            summary=summary,
            text_hash=text_hash,
        )

        try:
            self._queue.put_nowait(task)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def stats(self) -> dict:
        return {
            "queue_size": self._queue.qsize(),
            "processed": self.processed,
            "dropped": self.dropped,
            "workers": self.worker_threads,
        }

    def _worker_loop(self, scorer: SemanticScorer) -> None:
        timeout_s = self.batch_timeout_ms / 1000.0

        while not self._stop_event.is_set():
            try:
                first = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            batch = [first]
            deadline = time.perf_counter() + timeout_s

            while len(batch) < self.batch_size:
                if time.perf_counter() >= deadline:
                    break
                try:
                    item = self._queue.get_nowait()
                    batch.append(item)
                except queue.Empty:
                    break

            texts = [scorer.build_text(task.title, task.summary) for task in batch]
            scores = scorer.score_texts(texts)

            now = time.perf_counter()
            results: list[SemanticResult] = []
            for task, (score, anchor) in zip(batch, scores):
                queue_wait_ms = max(0.0, (now - task.enqueued_at) * 1000)
                results.append(
                    SemanticResult(
                        article_id=task.article_id,
                        semantic_score=score,
                        semantic_anchor=anchor,
                        queue_wait_ms=queue_wait_ms,
                    )
                )

            try:
                self.on_results(results)
            except Exception as exc:
                if self.logger:
                    self.logger.warning(f"Semantic callback failed: {exc}")

            self.processed += len(results)

            for _ in batch:
                self._queue.task_done()
