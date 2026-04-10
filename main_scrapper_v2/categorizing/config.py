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
# final_score = w1*semantic + w2*keyword + w3*entity + w4*event + w5*recency + w6*source
DEFAULT_RANKING_WEIGHTS = {
    "semantic": 0.30,
    "keyword": 0.18,
    "entity": 0.13,
    "event": 0.15,
    "recency": 0.14,
    "source": 0.08,
}

# Priority event weights used by the rule engine.
EVENT_WEIGHTS = {
    "ceo_change": 0.95,
    "earnings_surprise": 0.88,
    "dividend_actions": 0.7,
    "merger_acquisition": 0.9,
    "partnership_jointventure": 0.76,
    "investment_funding": 0.74,
    "lawsuit_regulation": 0.78,
    "war_sanctions": 0.92,
    "macro_shock": 0.84,
    "bankruptcy_default": 0.85,
    "supply_disruption": 0.75,
    "production_growth": 0.68,
    "commodity_price": 0.82,
    "credit_rating": 0.72,
    "loan_credit": 0.7,
    "product_launch": 0.6,
    "technology_disruption": 0.66,
    "demand_trend": 0.68,
    "capex_expansion": 0.64,
    "esg_event": 0.56,
    "health_crisis": 0.72,
    "analyst_actions": 0.6,
    "price_movement": 0.58,
}

# Rule-based event patterns (compiled once at startup).
EVENT_PATTERNS = {
    # MANAGEMENT / LEADERSHIP
    "ceo_change": [
        r"\b(ceo|chief executive|founder|chairman|md)\b.{0,40}\b(resigns?|steps?\s+down|quits?|retires?)\b",
        r"\b(new|appoints?|appointed|names?|named|replaces?)\b.{0,40}\b(ceo|chief executive|founder|chairman|md)\b",
    ],

    #EARNINGS / FINANCIAL PERFORMANCE
    "earnings_surprise": [
        r"\b(earnings|revenue|profit|ebitda|guidance)\b.{0,30}\b(beat|beats|above|tops|surge|jump)\b",
        r"\b(earnings|revenue|profit|guidance)\b.{0,30}\b(miss|misses|below|cuts?|slump|drop)\b",
    ],

    "dividend_actions": [
        r"\b(dividend|payout)\b.{0,20}\b(increase|cut|slash|declare|announce)\b",
        r"\b(stock\s+split|bonus\s+issue|buyback|share\s+repurchase)\b",
    ],

    #CORPORATE ACTIONS
    "merger_acquisition": [
        r"\b(merger|acquisition|takeover|buyout|stake\s+buy|acquire|acquires|acquired)\b",
    ],

    "partnership_jointventure": [
        r"\b(partnership|collaboration|joint\s+venture|tie[-\s]?up|strategic\s+alliance)\b",
    ],

    "investment_funding": [
        r"\b(invests?|investment|funding|raises?|raised|venture\s+capital|private\s+equity)\b",
    ],

    # LEGAL / REGULATORY
    "lawsuit_regulation": [
        r"\b(lawsuit|sues?|legal\s+action|probe|investigation|antitrust|penalty|fine)\b",
        r"\b(regulator|regulation|ban|banned|approval|compliance|watchdog)\b",
    ],

    # GEO-POLITICAL
    "war_sanctions": [
        r"\b(war|military|missile|airstrike|invasion|border\s+clash|ceasefire)\b",
        r"\b(sanction|sanctions|embargo|trade\s+war|tariff)\b",
    ],

    # MACRO ECONOMICS
    "macro_shock": [
        r"\b(inflation|cpi|ppi|gdp|recession|deflation|unemployment|payrolls)\b",
        r"\b(rate\s+hike|rate\s+cut|interest\s+rate|central\s+bank|monetary\s+policy|liquidity|repo\s+rate|rbi)\b",
    ],

    # CREDIT / DISTRESS
    "bankruptcy_default": [
        r"\b(bankruptcy|insolvency|default|debt\s+crisis|restructuring|credit\s+downgrade)\b",
    ],

    # SUPPLY / OPERATIONS
    "supply_disruption": [
        r"\b(supply\s+chain|shortage|disruption|logistics|shipping\s+crisis|factory\s+shutdown)\b",
    ],

    "production_growth": [
        r"\b(production|output|capacity)\b.{0,20}\b(increase|expand|ramp\s+up|scale)\b",
        r"\b(production|output)\b.{0,20}\b(decline|cut|halt|reduce)\b",
    ],

    # COMMODITY IMPACT (VERY IMPORTANT)
    "commodity_price": [
        r"\b(crude|oil|gold|silver|copper|steel|coal|gas)\b.{0,20}\b(rise|fall|surge|drop|spike)\b",
    ],

    # BANKING / FINANCE
    "credit_rating": [
        r"\b(rating\s+agency|moody'?s|fitch|s&p)\b.{0,20}\b(upgrade|downgrade)\b",
    ],

    "loan_credit": [
        r"\b(loan|credit|lending|npa|bad\s+loan)\b.{0,20}\b(rise|fall|increase|decrease)\b",
    ],

    # TECHNOLOGY / PRODUCT
    "product_launch": [
        r"\b(launch|unveil|introduce|roll\s+out)\b.{0,20}\b(product|service|platform)\b",
    ],

    "technology_disruption": [
        r"\b(ai|artificial\s+intelligence|automation|chip|semiconductor)\b",
    ],

    # DEMAND SIGNALS
    "demand_trend": [
        r"\b(demand|sales|orders)\b.{0,20}\b(strong|weak|surge|decline|drop)\b",
    ],

    # INFRA / CAPEX
    "capex_expansion": [
        r"\b(capex|capital\s+expenditure|expansion|new\s+plant|infrastructure)\b",
    ],

    # ESG / ENVIRONMENT
    "esg_event": [
        r"\b(esg|carbon|emissions|climate|sustainability|green\s+energy)\b",
    ],

    #  PANDEMIC / HEALTH SHOCKS
    "health_crisis": [
        r"\b(covid|pandemic|virus|lockdown|outbreak)\b",
    ],

    # MARKET SENTIMENT / ANALYST ACTIONS
    "analyst_actions": [
        r"\b(upgrade|downgrade|target\s+price|rating\s+cut|outperform|underperform)\b",
    ],

    # STOCK-SPECIFIC MOVES
    "price_movement": [
        r"\b(shares?|stock)\b.{0,20}\b(rise|fall|surge|plunge|drop)\b",
    ],
}

# Person role resolution keywords.
ENTITY_ROLE_PATTERNS = {
    "ceo_founder": [
        r"\bceo\b",
        r"\bchief\s+executive\b",
        r"\bfounder\b",
        r"\bco-?founder\b",
    ],
    "cfo_board": [
        r"\bcfo\b",
        r"\bchief\s+financial\s+officer\b",
        r"\bboard\b",
        r"\bdirector\b",
    ],
}

# Real-time impact scoring tuning for CPU execution.
DEFAULT_SEMANTIC_CONFIG = {
    "enabled": True,
    "model_name": "ProsusAI/finbert",
    "fallback_model_name": "sentence-transformers/all-MiniLM-L6-v2",
    "max_length": 96,
    "cache_size": 20000,
    "semantic_text_chars": 420,
    "ner_text_chars": 240,
    "spacy_enabled": True,
    "spacy_model": "en_core_web_sm",
    "recency_decay_hours": 18,
    "candidate_limit": 4000,
    "heuristic_boost": True,
    "dedup_top_n": True,
}
