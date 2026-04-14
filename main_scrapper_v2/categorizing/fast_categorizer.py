"""
Ultra-fast hybrid multi-label news categorization for real-time ingestion.

Design goals:
- Near-zero latency categorization during scrape ingestion
- Deterministic 1-3 labels with strict category set
- Thread-safe and cache-friendly for parallel workers
- Optional lightweight ML fallback only when confidence is low
"""

from __future__ import annotations

import os
import re
import threading
from urllib.parse import unquote, urlparse
from collections import OrderedDict, defaultdict
from functools import lru_cache
from pathlib import Path


STRICT_CATEGORIES: tuple[str, ...] = (
    "business",
    "markets",
    "politics",
    "india",
    "world",
    "others",
)

_CATEGORY_PRIORITY = {name: idx for idx, name in enumerate(STRICT_CATEGORIES)}


SOURCE_CATEGORY_MAP: dict[str, dict[str, float]] = {
    "moneycontrol": {"markets": 3.0, "business": 2.4, "india": 1.2},
    "economictimes": {"business": 2.9, "markets": 2.7, "india": 1.3},
    "livemint": {"business": 2.7, "markets": 2.1, "india": 1.2},
    "businessstandard": {"business": 2.8, "markets": 2.2, "india": 1.1},
    "etnow": {"markets": 2.8, "business": 2.2, "india": 1.2},
    "cnbctv18": {"markets": 2.8, "business": 2.3, "india": 1.3},
    "zeebusiness": {"markets": 2.7, "business": 2.2, "india": 1.3},
    "groww": {"markets": 2.8, "business": 2.0, "india": 1.2},
    "tradingview": {"markets": 2.5, "business": 1.5, "world": 0.7},
    "scanx": {"markets": 2.6, "business": 1.6, "india": 0.9},
    "angelone": {"markets": 2.7, "business": 1.9, "india": 1.0},
    "zerodha": {"markets": 2.5, "business": 1.8, "india": 1.0},
    "stockedge": {"markets": 2.5, "business": 1.8, "india": 1.0},
    "reuters": {"world": 2.2, "business": 1.0, "markets": 0.9},
    "cnbc": {"world": 2.2, "markets": 2.0, "business": 1.8},
    "bbc": {"world": 2.8, "politics": 1.8},
    "ndtv": {"india": 1.2, "politics": 0.7, "world": 0.5},
    "timesofindia": {"india": 1.0, "politics": 0.6, "world": 0.4},
    "rediff": {"india": 1.0, "politics": 0.6, "world": 0.4},
}


TOKEN_KEYWORDS: dict[str, frozenset[str]] = {
    "business": frozenset(
        {
            "business",
            "company",
            "companies",
            "corporate",
            "revenue",
            "profit",
            "loss",
            "margin",
            "valuation",
            "acquisition",
            "merger",
            "startup",
            "funding",
            "investment",
            "industry",
            "manufacturing",
            "board",
            "ceo",
            "cfo",
            "ipo",
            "stake",
            "deal",
            "contract",
            "bank",
            "lender",
            "credit",
        }
    ),
    "markets": frozenset(
        {
            "markets",
            "market",
            "stock",
            "stocks",
            "shares",
            "sensex",
            "nifty",
            "nasdaq",
            "dow",
            "forex",
            "trading",
            "rally",
            "plunge",
            "volatility",
            "bull",
            "bear",
            "index",
            "indices",
            "equity",
            "equities",
            "derivatives",
            "futures",
            "options",
            "bond",
            "yield",
            "commodities",
        }
    ),
    "politics": frozenset(
        {
            "politics",
            "election",
            "elections",
            "government",
            "parliament",
            "minister",
            "policy",
            "senate",
            "congress",
            "vote",
            "cabinet",
            "law",
            "bill",
            "diplomacy",
            "sanctions",
            "tariff",
            "war",
            "military",
            "geopolitical",
            "regulation",
        }
    ),
    "india": frozenset(
        {
            "india",
            "indian",
            "delhi",
            "mumbai",
            "bengaluru",
            "hyderabad",
            "chennai",
            "kolkata",
            "nse",
            "bse",
            "sebi",
            "rbi",
            "rupee",
            "bharat",
            "loksabha",
            "rajyasabha",
        }
    ),
    "world": frozenset(
        {
            "world",
            "global",
            "international",
            "us",
            "usa",
            "europe",
            "uk",
            "china",
            "japan",
            "russia",
            "ukraine",
            "middleeast",
            "g7",
            "g20",
            "imf",
            "worldbank",
            "federal",
            "fed",
            "ecb",
            "boe",
        }
    ),
    "others": frozenset(
        {
            "entertainment",
            "movie",
            "music",
            "sports",
            "cricket",
            "football",
            "celebrity",
            "education",
            "exam",
            "exams",
            "result",
            "results",
            "marks",
            "placement",
            "placements",
            "school",
            "college",
            "colleges",
            "campus",
            "lifestyle",
            "fashion",
            "travel",
            "weather",
            "festival",
            "health",
            "wellness",
        }
    ),
}


PHRASE_KEYWORDS: dict[str, frozenset[str]] = {
    "business": frozenset(
        {
            "quarterly earnings",
            "profit after tax",
            "operating margin",
            "capital expenditure",
            "business expansion",
            "merger and acquisition",
            "funding round",
        }
    ),
    "markets": frozenset(
        {
            "stock market",
            "share market",
            "market rally",
            "market crash",
            "sensex",
            "nifty 50",
            "fii flows",
            "dii flows",
            "open interest",
        }
    ),
    "politics": frozenset(
        {
            "general election",
            "state election",
            "foreign policy",
            "trade policy",
            "white house",
            "prime minister",
            "home minister",
        }
    ),
    "india": frozenset(
        {
            "in india",
            "indian economy",
            "government of india",
            "reserve bank of india",
            "securities and exchange board of india",
        }
    ),
    "world": frozenset(
        {
            "across the world",
            "around the world",
            "global markets",
            "international markets",
            "world leaders",
        }
    ),
    "others": frozenset(
        {
            "box office",
            "movie review",
            "campus placement",
            "education policy",
        }
    ),
}


INDIA_HINTS = frozenset(
    {
        "india",
        "indian",
        "new delhi",
        "mumbai",
        "bengaluru",
        "nse",
        "bse",
        "rbi",
        "sebi",
    }
)

WORLD_HINTS = frozenset(
    {
        "united states",
        "usa",
        "washington",
        "new york",
        "london",
        "beijing",
        "tokyo",
        "moscow",
        "brussels",
        "europe",
        "global",
        "international",
    }
)

ORG_HINT_TOKENS = frozenset(
    {
        "inc",
        "corp",
        "corporation",
        "ltd",
        "limited",
        "plc",
        "bank",
        "holdings",
        "industries",
        "technologies",
        "motors",
        "pharma",
        "group",
        "shares",
        "stock",
        "stocks",
    }
)


OFF_DOMAIN_TOKENS = frozenset(
    {
        "sports",
        "sport",
        "cricket",
        "football",
        "soccer",
        "ipl",
        "batting",
        "bowling",
        "match",
        "playoff",
        "entertainment",
        "movie",
        "movies",
        "film",
        "cinema",
        "actor",
        "actress",
        "celebrity",
        "bollywood",
        "hollywood",
        "music",
        "education",
        "exam",
        "exams",
        "marks",
        "school",
        "college",
        "colleges",
        "campus",
        "placement",
        "placements",
        "lifestyle",
        "quote",
        "love",
        "crime",
        "murder",
        "killed",
        "drown",
        "accident",
        "death",
        "weather",
        "horoscope",
    }
)

OFF_DOMAIN_PHRASES = frozenset(
    {
        "quote of the day",
        "walk of fame",
        "box office",
        "ott release",
        "points table",
        "how to check result",
        "board result",
        "exam result",
        "love quote",
        "died at",
    }
)

OFF_DOMAIN_STRONG_MARKERS = frozenset(
    {
        "sports",
        "sport",
        "cricket",
        "football",
        "soccer",
        "ipl",
        "movie",
        "movies",
        "film",
        "cinema",
        "celebrity",
        "education",
        "exam",
        "school",
        "college",
        "love",
        "accident",
        "murder",
        "killed",
        "drown",
        "death",
    }
)

FINANCE_SIGNAL_TOKENS = frozenset(
    {
        "market",
        "markets",
        "stock",
        "stocks",
        "share",
        "shares",
        "sensex",
        "nifty",
        "ipo",
        "earnings",
        "revenue",
        "profit",
        "loss",
        "margin",
        "dividend",
        "bank",
        "credit",
        "loan",
        "fund",
        "mutual",
        "bond",
        "yield",
        "forex",
        "rupee",
        "rbi",
        "sebi",
        "q1",
        "q2",
        "q3",
        "q4",
        "guidance",
        "valuation",
        "brokerage",
        "tender",
        "offer",
        "offers",
        "holding",
        "holdings",
        "acquisition",
        "acquire",
        "acquired",
        "merger",
        "stake",
        "shares",
        "results",
        "oil",
        "crude",
        "gold",
        "silver",
        "petrol",
        "diesel",
        "commodity",
        "commodities",
    }
)

FINANCE_SIGNAL_PHRASES = frozenset(
    {
        "stock market",
        "share price",
        "quarterly results",
        "quarterly earnings",
        "price target",
        "block deal",
        "buy rating",
        "sell rating",
    }
)

POLITICS_SIGNAL_TOKENS = frozenset(
    {
        "election",
        "elections",
        "manifesto",
        "government",
        "minister",
        "cabinet",
        "parliament",
        "senate",
        "policy",
        "crisis",
        "border",
        "security",
        "pact",
        "strategic",
        "alliance",
        "war",
        "ceasefire",
        "sanctions",
        "tariff",
        "diplomacy",
        "military",
    }
)


URL_SECTION_SCORE_MAP: dict[str, dict[str, float]] = {
    "markets": {"markets": 2.4, "business": 1.4},
    "market": {"markets": 2.2, "business": 1.2},
    "business": {"business": 2.2, "markets": 1.1},
    "companies": {"business": 2.0, "markets": 1.0},
    "industry": {"business": 2.0, "markets": 0.8},
    "economy": {"business": 1.8, "india": 0.8},
    "stock-market-news": {"markets": 2.5, "business": 1.2},
    "mutual-funds": {"markets": 2.3, "business": 1.1},
    "personal-finance": {"markets": 2.0, "business": 1.2, "india": 0.6},
    "sports": {"others": 3.4},
    "sport": {"others": 3.4},
    "cricket": {"others": 3.5},
    "entertainment": {"others": 3.3},
    "education": {"others": 3.4},
    "exams-results": {"others": 3.5},
    "health": {"others": 3.2},
    "relationships": {"others": 3.4},
    "technology": {"others": 2.6},
    "mobiles": {"others": 2.6},
    "lifestyle": {"others": 2.8},
    "auto": {"others": 2.2},
    "world-news": {"world": 2.2, "politics": 0.8},
    "india-news": {"india": 2.1, "politics": 0.9},
}

SOURCE_URL_SECTION_MAP: dict[str, dict[str, dict[str, float]]] = {
    "businessstandard": {
        "health": {"others": 4.0},
        "markets": {"markets": 2.6, "business": 1.6},
        "world-news": {"world": 2.3, "politics": 1.0},
    },
    "etnow": {
        "sports": {"others": 3.6},
        "technology": {"others": 3.0},
        "exams-results": {"others": 3.8},
        "entertainment": {"others": 3.5},
        "et-now-luxe": {"others": 3.2},
        "bizz-impact": {"others": 2.8},
        "auto": {"others": 2.6},
        "markets": {"markets": 2.8, "business": 1.8},
        "economy": {"business": 2.2, "india": 1.1},
        "companies": {"business": 2.2, "markets": 1.3},
        "mutual-funds": {"markets": 2.4, "business": 1.2},
        "personal-finance": {"markets": 2.2, "business": 1.2, "india": 0.8},
    },
    "ndtv": {
        "health": {"others": 3.6},
        "sports": {"others": 3.6},
        "cricket": {"others": 3.8},
        "mobiles": {"others": 2.8},
        "cities": {"others": 2.3, "india": 0.7},
        "india-news": {"india": 2.2, "politics": 1.0},
        "markets": {"markets": 2.4, "business": 1.5, "india": 0.9},
    },
    "reuters": {
        "sports": {"others": 3.8},
        "world": {"world": 2.4, "politics": 0.8},
        "business": {"business": 2.2, "markets": 1.2},
        "markets": {"markets": 2.3, "business": 1.1},
    },
    "livemint": {
        "entertainment": {"others": 3.5},
        "mint-lounge": {"others": 3.2},
    },
    "timesofindia": {
        "entertainment": {"others": 3.5},
        "education": {"others": 3.6},
        "sports": {"others": 3.6},
        "relationships": {"others": 3.6},
        "city": {"others": 2.4, "india": 0.8},
        "technology": {"others": 2.8},
    },
    "scanx": {
        "stock-market-news": {"markets": 2.7, "business": 1.3},
    },
    "groww": {
        "stocks": {"markets": 2.5, "business": 1.4, "india": 0.8},
    },
    "moneycontrol": {
        "news": {"business": 1.7, "markets": 1.2, "india": 0.8},
    },
    "tradingview": {
        "news": {"markets": 2.2, "business": 1.4},
    },
    "economictimes": {
        "markets": {"markets": 2.6, "business": 1.5},
        "industry": {"business": 2.1, "markets": 1.0},
        "news": {"india": 1.2, "politics": 0.9, "world": 0.8},
    },
}

URL_TOKEN_SCORE_MAP: dict[str, dict[str, float]] = {
    "sports": {"others": 2.0},
    "cricket": {"others": 2.1},
    "football": {"others": 2.1},
    "entertainment": {"others": 2.0},
    "education": {"others": 2.2},
    "exam": {"others": 2.2},
    "movie": {"others": 2.0},
    "movies": {"others": 2.0},
    "health": {"others": 2.0},
    "markets": {"markets": 1.4, "business": 0.6},
    "market": {"markets": 1.2, "business": 0.5},
    "stocks": {"markets": 1.4, "business": 0.5},
    "stock": {"markets": 1.2, "business": 0.4},
    "tender": {"markets": 1.1, "business": 0.8},
    "offer": {"markets": 1.0, "business": 0.7},
    "holding": {"business": 0.9, "markets": 0.6},
    "results": {"business": 0.9, "markets": 0.6},
    "business": {"business": 1.3, "markets": 0.5},
    "economy": {"business": 1.2, "india": 0.4},
    "politics": {"politics": 1.5, "india": 0.5},
    "crisis": {"world": 1.2, "politics": 1.0},
    "iran": {"world": 1.5, "politics": 1.0},
    "pakistan": {"world": 1.5, "politics": 1.0},
    "china": {"world": 1.4},
    "saudi": {"world": 1.4},
    "israel": {"world": 1.5, "politics": 1.0},
    "lebanon": {"world": 1.5, "politics": 1.0},
    "world": {"world": 1.5},
    "international": {"world": 1.3},
    "india": {"india": 1.3},
}


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+&.-]{1,30}")
_WS_RE = re.compile(r"\s+")


def _normalize_text(value: str) -> str:
    lowered = (value or "").strip().lower()
    return _WS_RE.sub(" ", lowered)


@lru_cache(maxsize=50000)
def _cached_tokens(normalized_text: str) -> frozenset[str]:
    if not normalized_text:
        return frozenset()

    raw_tokens = _TOKEN_RE.findall(normalized_text)
    compact: set[str] = set(raw_tokens)

    # Add joined alpha-numeric variants to improve matching for tokens like "middle east" -> "middleeast".
    for tok in list(compact):
        if tok.isalpha() and len(tok) > 2:
            compact.add(tok.replace("-", ""))

    return frozenset(compact)


class _ThreadSafeLRU:
    def __init__(self, max_size: int = 50000):
        self.max_size = max(5000, int(max_size))
        self._cache: OrderedDict[str, tuple[str, ...]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[str, ...] | None:
        with self._lock:
            value = self._cache.get(key)
            if value is None:
                return None
            self._cache.move_to_end(key)
            return value

    def set(self, key: str, value: tuple[str, ...]) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)


class _FallbackModel:
    """Optional lightweight fallback model loader.

    Supports either:
    - fastText supervised model (.bin/.ftz)
    - scikit Logistic Regression + TF-IDF vectorizer (joblib files)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._loaded = False
        self._backend = "none"
        self._fasttext_model = None
        self._lr_model = None
        self._tfidf = None

    @staticmethod
    def _label_to_category(label: str) -> str | None:
        value = (label or "").strip().lower()
        if value.startswith("__label__"):
            value = value[len("__label__") :]

        if value == "other":
            value = "others"

        if value in STRICT_CATEGORIES:
            return value
        return None

    @staticmethod
    def _candidate_paths() -> tuple[list[Path], list[Path]]:
        root = Path(__file__).resolve().parents[1]
        model_dir = root / "models"

        fasttext_paths: list[Path] = []
        sklearn_paths: list[Path] = []

        env_fasttext = os.getenv("FASTTEXT_CATEGORY_MODEL", "").strip()
        if env_fasttext:
            fasttext_paths.append(Path(env_fasttext))

        env_lr_model = os.getenv("CATEGORY_LR_MODEL", "").strip()
        env_tfidf = os.getenv("CATEGORY_TFIDF_MODEL", "").strip()
        if env_lr_model:
            sklearn_paths.append(Path(env_lr_model))
        if env_tfidf:
            sklearn_paths.append(Path(env_tfidf))

        fasttext_paths.extend(
            [
                model_dir / "news_category_fasttext.ftz",
                model_dir / "news_category_fasttext.bin",
            ]
        )
        sklearn_paths.extend(
            [
                model_dir / "news_category_lr.joblib",
                model_dir / "news_category_tfidf.joblib",
            ]
        )

        return fasttext_paths, sklearn_paths

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        with self._lock:
            if self._loaded:
                return

            fasttext_paths, sklearn_paths = self._candidate_paths()

            try:
                import fasttext  # type: ignore

                for path in fasttext_paths:
                    if path.exists() and path.suffix in {".bin", ".ftz"}:
                        self._fasttext_model = fasttext.load_model(str(path))
                        self._backend = "fasttext"
                        break
            except Exception:
                self._fasttext_model = None

            if self._backend == "none":
                try:
                    import joblib  # type: ignore

                    lr_model_path = None
                    tfidf_path = None
                    for path in sklearn_paths:
                        name = path.name.lower()
                        if "tfidf" in name and path.exists():
                            tfidf_path = path
                        elif "lr" in name and path.exists():
                            lr_model_path = path

                    if lr_model_path and tfidf_path:
                        self._lr_model = joblib.load(str(lr_model_path))
                        self._tfidf = joblib.load(str(tfidf_path))
                        self._backend = "logreg"
                except Exception:
                    self._lr_model = None
                    self._tfidf = None

            self._loaded = True

    def predict_scores(self, text: str) -> dict[str, float]:
        self._ensure_loaded()

        if not text:
            return {}

        if self._backend == "fasttext" and self._fasttext_model is not None:
            labels, probs = self._fasttext_model.predict(text, k=3)
            scores: dict[str, float] = {}
            for lbl, prob in zip(labels, probs):
                cat = self._label_to_category(lbl)
                if cat:
                    scores[cat] = max(scores.get(cat, 0.0), float(prob))
            return scores

        if self._backend == "logreg" and self._lr_model is not None and self._tfidf is not None:
            vec = self._tfidf.transform([text])
            if hasattr(self._lr_model, "predict_proba"):
                probas = self._lr_model.predict_proba(vec)[0]
                classes = list(self._lr_model.classes_)
                scores = {}
                for cls_name, prob in zip(classes, probas):
                    cat = self._label_to_category(str(cls_name))
                    if cat:
                        scores[cat] = max(scores.get(cat, 0.0), float(prob))
                return scores

            pred = self._lr_model.predict(vec)
            if len(pred) > 0:
                cat = self._label_to_category(str(pred[0]))
                if cat:
                    return {cat: 1.0}

        return {}


class HybridNewsCategorizer:
    """Deterministic hybrid categorizer optimized for ingestion-time latency."""

    def __init__(
        self,
        max_labels: int = 3,
        cache_size: int = 50000,
        fallback_threshold: float = 1.45,
    ):
        self.max_labels = max(1, min(3, int(max_labels)))
        self.fallback_threshold = float(fallback_threshold)
        self._result_cache = _ThreadSafeLRU(max_size=cache_size)
        self._fallback = _FallbackModel()

    @staticmethod
    def _normalize_source(source: str) -> str:
        return _normalize_text(source).replace(" ", "")

    @staticmethod
    def _compose_text(title: str, content: str, summary: str) -> str:
        return _normalize_text(f"{title}. {summary}. {content}")

    @staticmethod
    def _cache_key(source: str, title: str, summary: str, content: str, url: str = "") -> str:
        src = (source or "").strip().lower()
        title_k = (title or "").strip().lower()[:180]
        summary_k = (summary or "").strip().lower()[:220]
        content_k = (content or "").strip().lower()[:260]
        url_k = (url or "").strip().lower()[:220]
        return f"{src}|{title_k}|{summary_k}|{content_k}|{url_k}"

    @staticmethod
    def _url_to_signal_text(url: str) -> str:
        if not url:
            return ""

        try:
            parsed = urlparse(url)
            signal = f"{parsed.netloc} {parsed.path}"
        except Exception:
            signal = url

        signal = unquote(signal).lower()
        signal = signal.replace("-", " ").replace("_", " ").replace("/", " ")
        return _WS_RE.sub(" ", re.sub(r"[^a-z0-9 ]+", " ", signal)).strip()

    @staticmethod
    def _url_features(url: str) -> tuple[str, str, frozenset[str]]:
        if not url:
            return "", "", frozenset()

        try:
            parsed = urlparse(url)
            segments = [s for s in parsed.path.lower().split("/") if s]
        except Exception:
            segments = []

        first = segments[0] if segments else ""
        second = segments[1] if len(segments) > 1 else ""

        raw = " ".join(segments)
        tokens = set(re.findall(r"[a-z0-9]+", raw))
        if first:
            tokens.add(first.replace("-", ""))
        if second:
            tokens.add(second.replace("-", ""))
        return first, second, frozenset(tokens)

    @staticmethod
    def _domain_signals(title: str, content: str, summary: str = "") -> dict[str, int | bool]:
        text = HybridNewsCategorizer._compose_text(title, content, summary)
        if not text:
            return {
                "off_domain_hits": 0,
                "finance_hits": 0,
                "politics_hits": 0,
                "world_hits": 0,
                "hard_others": False,
            }

        tokens = _cached_tokens(text)

        off_domain_hits = len(tokens.intersection(OFF_DOMAIN_TOKENS))
        for phrase in OFF_DOMAIN_PHRASES:
            if phrase in text:
                off_domain_hits += 2

        finance_hits = len(tokens.intersection(FINANCE_SIGNAL_TOKENS))
        for phrase in FINANCE_SIGNAL_PHRASES:
            if phrase in text:
                finance_hits += 2

        politics_hits = len(tokens.intersection(POLITICS_SIGNAL_TOKENS))
        world_hits = 0
        for phrase in WORLD_HINTS:
            if " " in phrase:
                world_hits += int(phrase in text)
            elif phrase in tokens:
                world_hits += 1
        strong_off_domain_hits = len(tokens.intersection(OFF_DOMAIN_STRONG_MARKERS))

        # High off-domain with weak finance/politics indicates low-value feed noise.
        hard_others = (
            (strong_off_domain_hits >= 1 and finance_hits == 0 and politics_hits == 0 and world_hits == 0)
            or (off_domain_hits >= 4 and finance_hits <= 1 and politics_hits == 0 and world_hits == 0)
        )

        return {
            "off_domain_hits": off_domain_hits,
            "finance_hits": finance_hits,
            "politics_hits": politics_hits,
            "world_hits": world_hits,
            "hard_others": hard_others,
        }

    def classify_by_source(self, source: str) -> dict[str, float]:
        source_key = self._normalize_source(source)
        mapped = SOURCE_CATEGORY_MAP.get(source_key)
        if mapped is None:
            return {}
        return dict(mapped)

    def classify_by_keywords(self, title: str, content: str, summary: str = "") -> dict[str, float]:
        text = self._compose_text(title, content, summary)
        if not text:
            return {}

        tokens = _cached_tokens(text)
        scores: dict[str, float] = {}

        for category in STRICT_CATEGORIES:
            token_set = TOKEN_KEYWORDS[category]
            phrase_set = PHRASE_KEYWORDS[category]

            token_hits = len(tokens.intersection(token_set))
            if token_hits == 0 and not phrase_set:
                continue

            phrase_hits = 0
            for phrase in phrase_set:
                if phrase in text:
                    phrase_hits += 1

            raw_score = float(token_hits) + (1.6 * float(phrase_hits))
            if category == "others" and raw_score > 0.0:
                raw_score *= 1.35
            if raw_score > 0.0:
                scores[category] = raw_score

        return scores

    def classify_by_url(self, source: str, url: str) -> dict[str, float]:
        source_key = self._normalize_source(source)
        first, second, tokens = self._url_features(url)
        if not first and not tokens:
            return {}

        scores: dict[str, float] = defaultdict(float)

        generic_map = URL_SECTION_SCORE_MAP.get(first)
        if generic_map:
            for category, score in generic_map.items():
                scores[category] += float(score)

        source_map = SOURCE_URL_SECTION_MAP.get(source_key, {})
        source_section_scores = source_map.get(first)
        if source_section_scores:
            for category, score in source_section_scores.items():
                scores[category] += float(score)

        pair_key = f"{first}/{second}" if first and second else ""
        pair_map = source_map.get(pair_key)
        if pair_map:
            for category, score in pair_map.items():
                scores[category] += float(score)

        for token in tokens:
            token_map = URL_TOKEN_SCORE_MAP.get(token)
            if not token_map:
                continue
            for category, score in token_map.items():
                scores[category] += float(score)

        return dict(scores)

    def classify_by_ner(self, title: str, content: str, summary: str = "") -> dict[str, float]:
        text = self._compose_text(title, content, summary)
        if not text:
            return {}

        tokens = _cached_tokens(text)
        scores: dict[str, float] = {}

        india_hint_hits = 0
        for phrase in INDIA_HINTS:
            if " " in phrase:
                india_hint_hits += int(phrase in text)
            elif phrase in tokens:
                india_hint_hits += 1

        if india_hint_hits > 0:
            scores["india"] = min(1.8, 0.9 + (0.25 * india_hint_hits))

        world_hint_hits = 0
        for phrase in WORLD_HINTS:
            if " " in phrase:
                world_hint_hits += int(phrase in text)
            elif phrase in tokens:
                world_hint_hits += 1

        if world_hint_hits > 0:
            scores["world"] = min(1.8, 0.9 + (0.2 * world_hint_hits))

        org_hits = len(tokens.intersection(ORG_HINT_TOKENS))
        if org_hits > 0:
            scores["business"] = max(scores.get("business", 0.0), min(1.5, 0.7 + 0.2 * org_hits))
            scores["markets"] = max(scores.get("markets", 0.0), min(1.2, 0.5 + 0.15 * org_hits))

        return scores

    def fallback_model(self, title: str, content: str, summary: str = "") -> dict[str, float]:
        text = self._compose_text(title, content, summary)
        return self._fallback.predict_scores(text)

    @staticmethod
    def _merge_weighted_scores(
        source_scores: dict[str, float],
        keyword_scores: dict[str, float],
        url_scores: dict[str, float] | None,
        ner_scores: dict[str, float],
        fallback_scores: dict[str, float],
    ) -> dict[str, float]:
        merged: dict[str, float] = defaultdict(float)

        for category, score in source_scores.items():
            if category in _CATEGORY_PRIORITY:
                merged[category] += 1.0 * float(score)

        for category, score in keyword_scores.items():
            if category in _CATEGORY_PRIORITY:
                merged[category] += 0.62 * float(score)

        if url_scores:
            for category, score in url_scores.items():
                if category in _CATEGORY_PRIORITY:
                    merged[category] += 0.58 * float(score)

        for category, score in ner_scores.items():
            if category in _CATEGORY_PRIORITY:
                merged[category] += 0.48 * float(score)

        for category, score in fallback_scores.items():
            if category in _CATEGORY_PRIORITY:
                merged[category] += 0.95 * float(score)

        return dict(merged)

    def final_category_merge(
        self,
        source_scores: dict[str, float],
        keyword_scores: dict[str, float],
        url_scores: dict[str, float] | None = None,
        ner_scores: dict[str, float] | None = None,
        fallback_scores: dict[str, float] | None = None,
    ) -> list[str]:
        ner_scores = ner_scores or {}
        fallback_scores = fallback_scores or {}
        merged = self._merge_weighted_scores(
            source_scores=source_scores,
            keyword_scores=keyword_scores,
            url_scores=url_scores,
            ner_scores=ner_scores,
            fallback_scores=fallback_scores,
        )

        if not merged:
            return ["others"]

        others_score = merged.get("others", 0.0)
        best_non_others = max(
            (score for cat, score in merged.items() if cat != "others"),
            default=0.0,
        )

        # Prefer a clean fallback to "others" for clearly non-domain news.
        if others_score >= 1.35 and others_score >= (1.05 * best_non_others) and best_non_others < 2.6:
            return ["others"]

        ranked = sorted(
            merged.items(),
            key=lambda item: (-item[1], _CATEGORY_PRIORITY[item[0]]),
        )

        top_score = ranked[0][1]
        selected: list[str] = []

        for category, score in ranked:
            if score < 0.55:
                continue
            if score < top_score * 0.36:
                continue
            selected.append(category)
            if len(selected) >= self.max_labels:
                break

        if not selected:
            if top_score >= 0.35:
                selected = [ranked[0][0]]
            else:
                selected = ["others"]

        # Keep "others" as primary when it wins, otherwise remove it from mixed labels.
        if len(selected) > 1 and "others" in selected:
            if selected[0] == "others":
                selected = ["others"]
            else:
                selected = [cat for cat in selected if cat != "others"]

        if not selected:
            selected = ["others"]

        return selected[: self.max_labels]

    def classify(self, title: str, source: str, content: str = "", summary: str = "", url: str = "") -> dict[str, list[str]]:
        cache_key = self._cache_key(source=source, title=title, summary=summary, content=content, url=url)
        cached = self._result_cache.get(cache_key)
        if cached is not None:
            return {"categories": list(cached)}

        source_scores = self.classify_by_source(source)
        keyword_scores = self.classify_by_keywords(title=title, content=content, summary=summary)
        url_scores = self.classify_by_url(source=source, url=url)
        ner_scores = self.classify_by_ner(title=title, content=content, summary=summary)

        url_signal_text = self._url_to_signal_text(url)
        signal_content = f"{content} {url_signal_text}".strip()
        signals = self._domain_signals(title=title, content=signal_content, summary=summary)
        off_domain_hits = int(signals["off_domain_hits"])
        finance_hits = int(signals["finance_hits"])
        politics_hits = int(signals["politics_hits"])
        world_hits = int(signals["world_hits"])
        hard_others = bool(signals["hard_others"])
        url_others_score = float(url_scores.get("others", 0.0))
        non_others_evidence = max(
            [
                source_scores.get("business", 0.0),
                source_scores.get("markets", 0.0),
                source_scores.get("politics", 0.0),
                source_scores.get("world", 0.0),
                source_scores.get("india", 0.0),
                keyword_scores.get("business", 0.0),
                keyword_scores.get("markets", 0.0),
                keyword_scores.get("politics", 0.0),
                keyword_scores.get("world", 0.0),
                keyword_scores.get("india", 0.0),
                url_scores.get("business", 0.0),
                url_scores.get("markets", 0.0),
                url_scores.get("politics", 0.0),
                url_scores.get("world", 0.0),
                url_scores.get("india", 0.0),
                0.6 * float(finance_hits),
                0.7 * float(politics_hits),
                0.6 * float(world_hits),
            ]
        )

        if finance_hits <= 1:
            if "business" in source_scores:
                source_scores["business"] *= 0.35
            if "markets" in source_scores:
                source_scores["markets"] *= 0.35
            ner_scores.pop("business", None)
            ner_scores.pop("markets", None)

        if politics_hits == 0 and "politics" in source_scores:
            source_scores["politics"] *= 0.4

        if (
            off_domain_hits >= 1
            and finance_hits == 0
            and politics_hits == 0
            and world_hits == 0
            and non_others_evidence < 1.8
        ):
            source_scores = {}
            keyword_scores["others"] = max(
                keyword_scores.get("others", 0.0),
                1.9 + (0.15 * float(off_domain_hits)),
            )

        if hard_others or (
            off_domain_hits >= 5
            and finance_hits <= 2
            and politics_hits == 0
            and world_hits == 0
            and non_others_evidence < 2.0
        ):
            source_scores = {}
            keyword_scores["others"] = max(
                keyword_scores.get("others", 0.0),
                2.2 + (0.2 * float(off_domain_hits)),
            )
            if finance_hits <= 1:
                if keyword_scores.get("business", 0.0) < 2.0:
                    keyword_scores.pop("business", None)
                if keyword_scores.get("markets", 0.0) < 2.0:
                    keyword_scores.pop("markets", None)
                ner_scores.pop("business", None)
                ner_scores.pop("markets", None)

            result = ("others",)
            self._result_cache.set(cache_key, result)
            return {"categories": ["others"]}

        if (
            url_others_score >= 3.2
            and finance_hits == 0
            and politics_hits == 0
            and world_hits == 0
            and non_others_evidence < 1.7
        ):
            result = ("others",)
            self._result_cache.set(cache_key, result)
            return {"categories": ["others"]}

        provisional = self._merge_weighted_scores(
            source_scores=source_scores,
            keyword_scores=keyword_scores,
            url_scores=url_scores,
            ner_scores=ner_scores,
            fallback_scores={},
        )
        confidence = max(provisional.values(), default=0.0)

        fallback_scores: dict[str, float] = {}
        if confidence < self.fallback_threshold:
            fallback_scores = self.fallback_model(title=title, content=content, summary=summary)

        categories = self.final_category_merge(
            source_scores=source_scores,
            keyword_scores=keyword_scores,
            url_scores=url_scores,
            ner_scores=ner_scores,
            fallback_scores=fallback_scores,
        )

        result = tuple(categories)
        self._result_cache.set(cache_key, result)
        return {"categories": list(result)}

    def apply_to_article(self, article: dict) -> dict:
        title = article.get("news_caption") or article.get("title") or ""
        summary = article.get("news_summary") or ""
        content = article.get("content") or ""
        url = article.get("news_url") or ""
        source = article.get("source") or ""

        result = self.classify(title=title, source=source, content=content, summary=summary, url=url)
        categories = result["categories"]

        article["categories"] = categories
        article["category"] = categories[0] if categories else "others"
        return article


_CATEGORIZER_INSTANCE: HybridNewsCategorizer | None = None
_CATEGORIZER_LOCK = threading.Lock()


def get_news_categorizer() -> HybridNewsCategorizer:
    global _CATEGORIZER_INSTANCE
    if _CATEGORIZER_INSTANCE is None:
        with _CATEGORIZER_LOCK:
            if _CATEGORIZER_INSTANCE is None:
                _CATEGORIZER_INSTANCE = HybridNewsCategorizer()
    return _CATEGORIZER_INSTANCE


def classify_by_source(source: str) -> dict[str, float]:
    return get_news_categorizer().classify_by_source(source)


def classify_by_keywords(title: str, content: str, summary: str = "") -> dict[str, float]:
    return get_news_categorizer().classify_by_keywords(title=title, content=content, summary=summary)


def classify_by_ner(title: str, content: str, summary: str = "") -> dict[str, float]:
    return get_news_categorizer().classify_by_ner(title=title, content=content, summary=summary)


def fallback_model(title: str, content: str, summary: str = "") -> dict[str, float]:
    return get_news_categorizer().fallback_model(title=title, content=content, summary=summary)


def final_category_merge(
    source_scores: dict[str, float],
    keyword_scores: dict[str, float],
    ner_scores: dict[str, float],
    fallback_scores: dict[str, float],
    url_scores: dict[str, float] | None = None,
) -> list[str]:
    return get_news_categorizer().final_category_merge(
        source_scores=source_scores,
        keyword_scores=keyword_scores,
        url_scores=url_scores,
        ner_scores=ner_scores,
        fallback_scores=fallback_scores,
    )


def categorize_article(title: str, source: str, content: str = "", summary: str = "", url: str = "") -> dict[str, list[str]]:
    return get_news_categorizer().classify(title=title, source=source, content=content, summary=summary, url=url)
