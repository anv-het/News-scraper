"""
Top news module for ranking articles.

Maintains a global top 100 news list based on relevance scoring.

Components:
  - config: Boost keywords and source importance weights for ranking
  - top_news: Top 100 article management with relevance scoring
"""

from categorizing.top_news import TopNewManager
from categorizing.semantic_scoring import SemanticScorer, AsyncSemanticWorker, MiniLMEmbedder
from categorizing.realtime_impact import RealTimeImpactScorer

__all__ = [
    "TopNewManager",
    "SemanticScorer",
    "AsyncSemanticWorker",
    "MiniLMEmbedder",
    "RealTimeImpactScorer",
]
