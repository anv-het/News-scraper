"""
Top news ranking configuration.

Keywords that boost top news ranking and source importance weights.
"""

# Keywords that boost top news ranking (politics, stocks, economy themes)
TOP_NEWS_BOOST_KEYWORDS = {
    # --- Politics & Geopolitics ---
    "politics": 0.25,
    "election": 0.22,
    "government": 0.20,
    "parliament": 0.15,
    "minister": 0.15,
    "policy": 0.22,
    "sanctions": 0.25,
    "trade war": 0.25,
    "tariffs": 0.22,
    "geopolitics": 0.22,
    "diplomacy": 0.12,

    # --- Conflict / Risk ---
    "war": 0.30,
    "military": 0.18,
    "conflict": 0.18,
    "crisis": 0.22,
    "emergency": 0.25,
    "terror": 0.25,
    "attack": 0.22,

    # --- Macroeconomics ---
    "economy": 0.22,
    "recession": 0.25,
    "inflation": 0.22,
    "deflation": 0.18,
    "gdp": 0.20,
    "growth": 0.18,
    "slowdown": 0.22,
    "economic data": 0.20,
    "cpi": 0.25,
    "ppi": 0.20,
    "unemployment": 0.22,
    "jobs report": 0.25,
    "payrolls": 0.25,
    "consumer spending": 0.18,

    # --- Central Banks & Rates ---
    "interest rate": 0.30,
    "rate hike": 0.30,
    "rate cut": 0.30,
    "fed": 0.30,
    "central bank": 0.28,
    "monetary policy": 0.25,
    "tightening": 0.22,
    "quantitative easing": 0.25,
    "liquidity": 0.20,
    "bond yields": 0.25,

    # --- Markets & Finance ---
    "stocks": 0.28,
    "stock market": 0.30,
    "market": 0.22,
    "financial": 0.18,
    "trading": 0.20,
    "volatility": 0.25,
    "selloff": 0.28,
    "rally": 0.22,
    "correction": 0.25,
    "bull market": 0.18,
    "bear market": 0.22,
    "valuation": 0.18,

    # --- Corporate / Business ---
    "earnings": 0.30,
    "earnings report": 0.30,
    "revenue": 0.22,
    "profit": 0.22,
    "guidance": 0.25,
    "forecast": 0.20,
    "downgrade": 0.25,
    "upgrade": 0.22,
    "merger": 0.28,
    "acquisition": 0.28,
    "ipo": 0.25,
    "bankruptcy": 0.30,
    "default": 0.30,
    "layoffs": 0.25,
    "restructuring": 0.22,

    # --- Commodities ---
    "oil": 0.28,
    "crude": 0.28,
    "gold": 0.22,
    "commodity": 0.22,
    "gas": 0.22,
    "energy crisis": 0.28,
    "supply shock": 0.28,

    # --- Supply Chain ---
    "supply chain": 0.25,
    "shortage": 0.25,
    "disruption": 0.25,
    "logistics": 0.18,
    "shipping": 0.18,

    # --- Risk / Panic Signals ---
    "breaking": 0.28,
    "urgent": 0.18,
    "alert": 0.18,
    "panic": 0.22,
    "fear": 0.20,
    "uncertainty": 0.20,

    # --- Disasters ---
    "disaster": 0.22,
    "natural disaster": 0.25,
    "earthquake": 0.25,
    "flood": 0.22,
    "hurricane": 0.25,
    "wildfire": 0.22,

    # --- Currency / Forex ---
    "currency": 0.22,
    "forex": 0.22,
    "exchange rate": 0.25,
    "dollar": 0.25,
    "rupee": 0.22,
    "devaluation": 0.28,

    # --- Tech / Sector-Specific ---
    "ai": 0.20,
    "semiconductor": 0.25,
    "chip": 0.25,
    "technology": 0.18,
    "regulation": 0.25,
    "antitrust": 0.25,

    # --- Extreme Events ---
    "crash": 0.30,
    "collapse": 0.30,
    "bubble": 0.25,
    "meltdown": 0.30,
}

# Source importance weights (defaults, can be overridden in sites.yaml)
DEFAULT_SOURCE_WEIGHTS = {
    # High authority sources
    "reuters": 1.5,
    "bbc": 1.5,
    "ap": 1.5,
    "ft": 1.5,  # Financial Times
    # Quality financial sources
    "moneycontrol": 1.3,
    "livemint": 1.3,
    "economictimes": 1.3,
    "bloomberg": 1.4,
    "cnbc": 1.3,
    "zerodha": 1.3,
    "groww": 1.2,
    # Default weight for unlisted sources
}

# Final ranking weights:
# final_score = w1*keyword + w2*recency + w3*source + w4*semantic
DEFAULT_RANKING_WEIGHTS = {
    "keyword": 0.29,
    "recency": 0.32,
    "source": 0.05,
    "semantic": 0.27,
}

# Semantic scoring pipeline tuning for CPU execution.
DEFAULT_SEMANTIC_CONFIG = {
    "enabled": True,
    "model_name": "sentence-transformers/all-MiniLM-L6-v2",
    "max_length": 96,
    "cache_size": 20000,
    "batch_size": 32,
    "batch_timeout_ms": 25,
    "queue_maxsize": 20000,
    "worker_threads": 2,
    "candidate_limit": 4000,
    "heuristic_boost": True,
    "use_faiss_if_available": True,
}
