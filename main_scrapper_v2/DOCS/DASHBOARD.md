# News Scrapper — Dashboard Documentation

## Overview

A production-ready single-page web dashboard that displays news collected by the scrapper,
with real-time updates, filtering, sorting, and semantic search.

---

## Access

### Option A: Built-in Server (recommended)
When `main.py` is running with `DASHBOARD_ENABLED=true`:
```
http://localhost:8080
```
The Python HTTP server serves both the dashboard files and the API endpoints.

### Option B: VS Code Live Server / Any Static Server
Open `dashboard/index.html` in any web server. The dashboard
auto-detects it's not on port 8080 and connects to `http://localhost:8080` for API calls.

> **Note**: `main.py` must still be running for the API to be available.

---

## Features

### Real-Time IST Clock
Top-right corner shows current date/time in IST, updating every second.

### Stats Bar
Five cards showing:
- **Total Articles**: All-time count across all sources
- **Today**: Articles collected today
- **Active Sources**: `healthy/total` worker count
- **Uptime**: How long main.py has been running
- **Last Updated**: Last dashboard refresh time

### Source Health Cards
One card per source showing:
- Source name and health status badge (healthy/degraded/blocked)
- Total articles and today's count
- Poll interval and error count

### Source Filter Tabs
Click a source name to filter news to that source only. "All Sources" shows everything.

### Date Filter
Calendar picker — select any date to see news from that day. Defaults to today.

### Sort Options
- **Newest First**: Default, most recent articles at top
- **Oldest First**: Chronological order
- **By Source**: Grouped by source, then by time

### Semantic Search (Fuse.js)
The search bar uses **fuzzy/semantic matching** powered by Fuse.js:
- Searches across caption, summary, source name, and URL
- Typo-tolerant (e.g., "tarding" matches "trading")
- Weighted: headline matches rank higher than URL matches
- Real-time filtering as you type

### Theme Toggle
🌙 / ☀️ button switches between dark and light themes. Preference saved in localStorage.

---

## News Cards

Each article displays:
- **Source badge** — colored by source (top-right)
- **Headline** — clickable link to original article (opens in new tab)
- **Summary** — first 2 lines, truncated with ellipsis
- **Time ago** — computed live in the browser (not from scraped data)
- **Date/time** — publication date and time in IST
- **Scraped at** — when the scrapper fetched this article

---

## Auto-Refresh

The dashboard refreshes every **10 seconds**:
- Fetches latest stats
- Fetches latest news for current filter/date
- Updates health cards
- Recomputes "time ago" for all visible articles

---

## Responsive Design

The dashboard works on:
- **Desktop**: Full layout with side-by-side cards
- **Tablet**: Cards wrap, reduced padding
- **Mobile**: Single-column layout, smaller fonts

---

## Customization

### Adding Source Colors

Edit `dashboard/style.css` and add a rule matching `source-<name>`:

```css
.source-mynewsource {
    background: rgba(255, 100, 0, 0.15);
    color: #ff6400;
}
```

### Changing Refresh Rate

In `dashboard/app.js`:
```javascript
const REFRESH_INTERVAL = 10_000;  // milliseconds
```

### Changing API Port

If you change `DASHBOARD_PORT` in `.env`, update `dashboard/app.js`:
```javascript
const API_PORT = 8080;  // match your .env setting
```

---

## Architecture

```
Browser
   │
   ├── index.html  ← Structure
   ├── style.css   ← Dark/light theme, responsive layout
   └── app.js      ← API calls, Fuse.js search, rendering
         │
         ├── fetchStats()   → GET /api/stats
         ├── fetchSources() → GET /api/sources
         ├── fetchNews()    → GET /api/news?date=...&source=...
         │
         └── Renders:
             ├── Stats bar
             ├── Health cards
             ├── Source tabs
             └── News feed cards
```

No build tools, no frameworks, no npm — pure HTML/CSS/JS with one external library (Fuse.js via CDN).
