# 📑 Documentation Index

Complete documentation for the News Scrapper project.

## Getting Started

| Document | Description |
|----------|-------------|
| [QUICKSTART.md](QUICKSTART.md) | Installation, configuration, and first run |
| **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)** | **Current status: what's working, incomplete features, known limitations** |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, project structure, component design |

## Complete Reference

| Document | Description |
|----------|-------------|
| [FLOW.md](FLOW.md) | Detailed data flow, worker loops, dedup strategy |
| [CONFIGURATION.md](CONFIGURATION.md) | Complete reference for `.env`, `sites.yaml`, `proxies.txt`, API endpoints |
| [SOURCES.md](SOURCES.md) | Deep dive into each scraper: how they work, rate limits, data quality |
| [ADDING_SOURCES.md](ADDING_SOURCES.md) | Step-by-step guide to add a new news source |
| [STORAGE.md](STORAGE.md) | JSON schema, dedup layers, atomic writes, Redis structures, file sizes |
| [DASHBOARD.md](DASHBOARD.md) | Dashboard features, access methods, customization |
| [RESILIENCE.md](RESILIENCE.md) | Health states, error handling, blocked recovery, long-running stability |
| [PROXY_GUIDE.md](PROXY_GUIDE.md) | Proxy configuration, rotation, bandwidth management, anti-block strategies |
| [LOGGING.md](LOGGING.md) | Log levels, file rotation, color coding, log interpretation |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Running as Windows service, systemd, Docker, production monitoring |
| [CATEGORIZATION.md](CATEGORIZATION.md) | Hybrid real-time categorization system (implemented) |
