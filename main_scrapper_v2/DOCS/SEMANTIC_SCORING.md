# Semantic Scoring Module

## Overview

The top-news pipeline now supports asynchronous semantic relevance scoring:

Scraper -> Basic Ranking -> Priority Queue -> Semantic Worker -> Score Update

Basic ranking remains synchronous and fast. Semantic scoring is applied later by CPU workers.

## Final Score Formula

final_score = (w1 * keyword_score) + (w2 * recency_score) + (w3 * source_score) + (w4 * semantic_score)

Default weights are defined in categorizing/config.py:
- keyword: 0.28
- recency: 0.32
- source: 0.15
- semantic: 0.25

## Semantic Anchors

Anchors are hardcoded in categorizing/semantic_scoring.py and include:
- interest rate changes
- earnings results
- mergers and acquisitions
- geopolitical events
- commodity price changes
- regulations and bans
- war / political events

## Performance Features

- MiniLM encoder on CPU
- Batch embedding with micro-batches
- LRU embedding cache to skip duplicate headlines
- Priority queue for impact-first processing
- Async workers to avoid blocking scraper threads
- Optional FAISS acceleration if faiss is available

## Runtime Configuration

Environment variables in main.py:
- SEMANTIC_ENABLED
- SEMANTIC_BATCH_SIZE
- SEMANTIC_BATCH_TIMEOUT_MS
- SEMANTIC_QUEUE_MAXSIZE
- SEMANTIC_CACHE_SIZE
- SEMANTIC_WORKER_THREADS
- SEMANTIC_MODEL
- SEMANTIC_CANDIDATE_LIMIT

## Example

Run:
python categorizing/semantic_example.py

This demonstrates immediate ranking followed by semantic score updates.
