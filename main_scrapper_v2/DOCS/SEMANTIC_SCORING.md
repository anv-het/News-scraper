# Real-Time Impact Scoring

## Overview

The top-news ranking path now performs synchronous per-item scoring with no semantic queue:

Scraper -> Impact Scorer -> Top-N Exact-Title Dedup -> Ranked Output

Each item is scored immediately on arrival using CPU-only components preloaded in memory.

## Final Score Formula

final_score =
		w1 * semantic_score +
		w2 * entity_score +
		w3 * event_score +
		w4 * recency_score +
		w5 * source_score

Default weights in categorizing/config.py:
- semantic: 0.34
- entity: 0.20
- event: 0.23
- recency: 0.15
- source: 0.08

## Scoring Components

1. Semantic scoring
- MiniLM sentence encoder on CPU
- Concept vectors built from TOP_NEWS_BOOST_KEYWORDS and finance event anchors
- LRU embedding cache for duplicate texts

2. NER and entity impact
- ORG, PERSON, GPE extraction via spaCy when available
- Heuristic fallback extractor when spaCy model is unavailable
- Entity impact weights:
	- company mention: +0.5
	- CEO/founder person context: +0.7
	- CFO/board person context: +0.4
	- generic person: +0.1

3. Event detection
- Rule-based event matcher for:
	- CEO changes
	- earnings surprises
	- mergers/acquisitions
	- lawsuits/regulatory actions
	- war/sanctions
	- macro shocks (inflation, CPI/PPI, GDP, rates)
	- bankruptcy/default
	- supply disruption

4. Recency and source scoring
- Exponential time decay
- Source normalization against configured source weights

## Deduplication Rule

Strict deduplication is applied for top-ranked output:
- For exact same title strings, only highest scoring item is retained in top N
- Candidate pool is not globally purged
- Dedup occurs after scoring and before returning ranked list

## Runtime Configuration

Core model and scorer env vars:
- SEMANTIC_ENABLED
- SEMANTIC_MODEL
- SEMANTIC_CACHE_SIZE
- SEMANTIC_CANDIDATE_LIMIT
- SEMANTIC_TEXT_CHARS
- NER_TEXT_CHARS
- SPACY_ENABLED
- SPACY_MODEL
- RECENCY_DECAY_HOURS
- TOPNEWS_DEDUP_TOP_N

Ranking weight env vars:
- RANK_WEIGHT_SEMANTIC
- RANK_WEIGHT_ENTITY
- RANK_WEIGHT_EVENT
- RANK_WEIGHT_RECENCY
- RANK_WEIGHT_SOURCE

## Example

Run:
python categorizing/realtime_example.py

The script scores sample items and shows top-N exact-title dedup behavior.
