/* ═══════════════════════════════════════════════════════════════════
   NEWS SCRAPPER DASHBOARD — Application Logic
   Fetches data from REST API, renders news cards, handles
   search/filter/sort with Fuse.js semantic matching.
   ═══════════════════════════════════════════════════════════════════ */

// API target is resolved from backend runtime config generated from .env.
const API_BASE = (() => {
    const loc = window.location;
    const cfg = window.__DASHBOARD_CONFIG__ || {};

    // If dashboard is served over HTTP(S), API is same origin.
    if (loc.protocol === 'http:' || loc.protocol === 'https:') {
        return loc.origin;
    }

    // Fallback for non-http contexts (for example file:// preview).
    if (cfg.port) {
        const host = (cfg.host && cfg.host !== '0.0.0.0') ? cfg.host : (loc.hostname || 'localhost');
        return `http://${host}:${cfg.port}`;
    }

    return 'http://localhost';
})();
const REFRESH_INTERVAL = 10_000;  // 10 seconds
const TOP_NEWS_REFRESH_INTERVAL = 2_000; // 2 seconds for live top-news updates
const CLOCK_INTERVAL = 1_000;

let allNews = [];
let topNews = [];
let fuseInstance = null;
let currentSource = 'all';
let currentSort = 'newest';
let isTopNewsMode = false;
let sources = [];
let statsData = {};
let topNewsRefreshTimer = null;
let topNewsFingerprint = '';

const SOURCE_LINKS = {
    groww: 'https://groww.in/market-news/stocks',
    livemint: 'https://www.livemint.com/latest-news',
    scanx: 'https://scanx.trade/stock-market-news/latest-news',
    tradingview: 'https://in.tradingview.com/news-flow/',
    moneycontrol: 'https://www.moneycontrol.com/news/',
    angelone: 'https://www.angelone.in/news',
    cnbctv18: 'https://www.cnbctv18.com/latest-news/',
    reuters: 'https://www.reuters.com/',
    cnbc: 'https://www.cnbc.com/world-markets/',
    bbc: 'https://www.bbc.com/news',
    economictimes: 'https://economictimes.indiatimes.com/news/latest-news',
    zeebusiness: 'https://www.zeebiz.com/latest-news',
    etnow: 'https://www.etnownews.com/latest-news',
    businessstandard: 'https://www.business-standard.com/latest-news',
    ndtv: 'https://www.ndtv.com/latest',
    timesofindia: 'https://timesofindia.indiatimes.com',
};

// ─── Initialization ─────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initClock();
    initTheme();
    initSidebar();
    initEventListeners();
    setTodayDate();
    fetchAll();
    setInterval(fetchAll, REFRESH_INTERVAL);
});

// ─── Clock ──────────────────────────────────────────────────────────

function initClock() {
    updateClock();
    setInterval(updateClock, CLOCK_INTERVAL);
}

function updateClock() {
    const now = new Date();
    const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
    const opts = {
        weekday: 'short', year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true,
    };
    document.getElementById('clock').textContent = ist.toLocaleString('en-IN', opts) + ' IST';
}

// ─── Theme ──────────────────────────────────────────────────────────

function initTheme() {
    const saved = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
    document.getElementById('themeToggle').textContent = saved === 'dark' ? '🌙' : '☀️';
    document.getElementById('themeToggle').addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
        document.getElementById('themeToggle').textContent = next === 'dark' ? '🌙' : '☀️';
    });
}

// ─── Sidebar ────────────────────────────────────────────────────────

function initSidebar() {
    const saved = localStorage.getItem('sidebarOpen');
    if (saved === 'true') {
        document.body.classList.add('sidebar-open');
    }

    document.getElementById('sidebarToggle').addEventListener('click', toggleSidebar);
    document.getElementById('sidebarClose').addEventListener('click', toggleSidebar);
    document.getElementById('sidebarFilter').addEventListener('input', () => renderSidebar());

    updateSidebarArrow();
}

function toggleSidebar() {
    document.body.classList.toggle('sidebar-open');
    const isOpen = document.body.classList.contains('sidebar-open');
    localStorage.setItem('sidebarOpen', isOpen);
    updateSidebarArrow();
}

function updateSidebarArrow() {
    const isOpen = document.body.classList.contains('sidebar-open');
    document.getElementById('sidebarArrow').textContent = isOpen ? '▶' : '◀';
}

// ─── Event Listeners ────────────────────────────────────────────────

function initEventListeners() {
    document.getElementById('searchInput').addEventListener('input', debounce(onFilterChange, 200));
    document.getElementById('dateFilter').addEventListener('change', fetchNews);
    document.getElementById('sortSelect').addEventListener('change', (e) => {
        currentSort = e.target.value;
        renderNews();
    });
}

function setTodayDate() {
    const now = new Date();
    const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
    const y = ist.getFullYear();
    const m = String(ist.getMonth() + 1).padStart(2, '0');
    const d = String(ist.getDate()).padStart(2, '0');
    document.getElementById('dateFilter').value = `${y}-${m}-${d}`;
}

// ─── Data Fetching ──────────────────────────────────────────────────

async function fetchAll() {
    await Promise.all([
        fetchStats(),
        fetchSources(),
        fetchNews(),
        fetchTopNews({ renderIfVisible: isTopNewsMode }),
    ]);
    buildFuseIndex();
}

async function fetchStats() {
    try {
        const resp = await fetch(`${API_BASE}/api/stats`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        statsData = await resp.json();
        renderStats();
    } catch (e) {
        console.error('Failed to fetch stats:', e);
    }
}

async function fetchSources() {
    try {
        const resp = await fetch(`${API_BASE}/api/sources`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        sources = await resp.json();
        renderSidebar();
    } catch (e) {
        console.error('Failed to fetch sources:', e);
    }
}

async function fetchNews() {
    const dateVal = document.getElementById('dateFilter').value || '';
    const url = `${API_BASE}/api/news?limit=500${dateVal ? `&date=${dateVal}` : ''}`;
    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        allNews = await resp.json();
        renderNews();
    } catch (e) {
        console.error('Failed to fetch news:', e);
        const loadingEl = document.getElementById('loading');
        if (loadingEl) loadingEl.innerHTML = '<p>Failed to load news. Is the server running?</p>';
    }
}

async function fetchTopNews(options = {}) {
    const { renderIfVisible = false } = options;
    try {
        const resp = await fetch(`${API_BASE}/api/top-news`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const incoming = await resp.json();
        const nextFingerprint = fingerprintTopNews(incoming);
        const changed = nextFingerprint !== topNewsFingerprint;

        topNews = incoming;
        topNewsFingerprint = nextFingerprint;

        if (renderIfVisible && isTopNewsMode && changed) {
            renderTopNews(topNews);
        }
    } catch (e) {
        console.error('Failed to fetch top news:', e);
        topNews = [];
    }
}

function startTopNewsLiveUpdates() {
    if (topNewsRefreshTimer) return;
    topNewsRefreshTimer = setInterval(() => {
        fetchTopNews({ renderIfVisible: true });
    }, TOP_NEWS_REFRESH_INTERVAL);
}

function stopTopNewsLiveUpdates() {
    if (!topNewsRefreshTimer) return;
    clearInterval(topNewsRefreshTimer);
    topNewsRefreshTimer = null;
}

// ─── Fuse.js Semantic Search ────────────────────────────────────────

function buildFuseIndex() {
    fuseInstance = new Fuse(allNews, {
        keys: [
            { name: 'news_caption', weight: 0.5 },
            { name: 'news_summary', weight: 0.3 },
            { name: 'source', weight: 0.1 },
            { name: 'news_url', weight: 0.1 },
        ],
        threshold: 0.4,
        distance: 200,
        includeScore: true,
        minMatchCharLength: 2,
    });
}

// ─── Rendering ──────────────────────────────────────────────────────

function renderSidebar() {
    const container = document.getElementById('sidebarSources');
    const workers = statsData.workers || {};
    const srcStats = statsData.sources || {};
    const filterText = (document.getElementById('sidebarFilter')?.value || '').toLowerCase();

    let html = `
        <div class="sidebar-mode-row">
            <div class="sidebar-source-card ${!isTopNewsMode && currentSource === 'all' ? 'active' : ''}" data-source="all">
                <div class="sidebar-source-header">
                    <span class="sidebar-source-name">🌐 All Sources</span>
                </div>
            </div>
            <button class="sidebar-top-news-btn ${isTopNewsMode ? 'active' : ''}" type="button" data-action="top-news" title="Show Top 100 News">⭐ Top News</button>
        </div>`;

    for (const src of sources) {
        if (filterText && !src.name.toLowerCase().includes(filterText) && !src.display_name.toLowerCase().includes(filterText)) {
            continue;
        }

        const isActive = currentSource === src.name;
        const worker = workers[src.name];
        const status = worker?.status || 'unknown';
        const statusColor = status === 'healthy' ? 'green' : status === 'blocked' ? 'red' : 'yellow';

        html += `
        <div class="sidebar-source-card ${isActive ? 'active' : ''}" data-source="${src.name}">
            <div class="sidebar-source-header">
                <span class="sidebar-source-name">${escapeHtml(src.display_name)}</span>
                <span class="source-status status-${statusColor}" title="${status}">●</span>
            </div>
            <div class="sidebar-source-meta">
                <span>${worker?.total_fetched || 0} articles</span>
            </div>
        </div>`;
    }

    container.innerHTML = html;

    // Attach event listeners
    container.querySelectorAll('.sidebar-source-card').forEach(card => {
        card.addEventListener('click', () => {
            currentSource = card.dataset.source;
            setTopNewsMode(false);
            renderSidebar();
            renderNews();
        });
    });

    container.querySelectorAll('[data-action="top-news"]').forEach(btn => {
        btn.addEventListener('click', () => {
            setTopNewsMode(!isTopNewsMode);
        });
    });

    document.getElementById('sidebarSourceCount').textContent = sources.length;
}

function renderStats() {
    const stats = statsData || {};
    const uptime = stats.uptime_seconds || 0;
    const updated = new Date().toLocaleTimeString('en-IN');

    document.getElementById('totalArticles').textContent = stats.total_articles || '—';
    document.getElementById('todayArticles').textContent = stats.today_articles || 0;
    document.getElementById('activeSources').textContent = Object.keys(stats.workers || {}).length;
    document.getElementById('uptime').textContent = formatUptime(uptime);
    document.getElementById('lastUpdated').textContent = updated;

    const activeSourceLabel = isTopNewsMode
        ? '⭐ Top News'
        : currentSource === 'all'
            ? 'All Sources'
            : sources.find(s => s.name === currentSource)?.display_name || currentSource;
    document.getElementById('activeSourceLabel').textContent = activeSourceLabel;
}

function renderNews() {
    const container = document.getElementById('newsFeed');
    const items = getFilteredNews();

    if (!items || items.length === 0) {
        container.innerHTML = '<div class="no-results">No news articles found.</div>';
        return;
    }

    let html = '';
    for (const item of items) {
        const src = item.source || '';
        const timeAgo = computeTimeAgo(item);
        const url = item.news_url || '#';
        const summary = item.news_summary || '';
        const imageUrl = item.image_url || '';

        const imageHtml = imageUrl
            ? `<div class="news-thumb">
                   <a href="${escapeHtml(url)}" target="_blank" rel="noopener">
                       <img src="${escapeHtml(imageUrl)}" alt="" loading="lazy" onerror="this.parentElement.parentElement.style.display='none'">
                   </a>
               </div>`
            : '';

        html += `
        <article class="news-card ${imageUrl ? 'has-image' : ''}">
            <div class="news-card-body">
                ${imageHtml}
                <div class="news-card-content">
                    <div class="news-card-header">
                        <div class="news-caption">
                            <a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(item.news_caption || 'Untitled')}</a>
                        </div>
                        <span class="news-source-badge source-${src}">${getDisplayName(src)}</span>
                    </div>
                    ${summary ? `<div class="news-summary">${escapeHtml(summary)}</div>` : ''}
                    <div class="news-meta">
                        <span class="news-meta-item time-ago">⏱ ${timeAgo}</span>
                        <span class="news-meta-item">📅 ${item.news_date || ''}</span>
                        <span class="news-meta-item">🕐 ${item.news_time || ''}</span>
                        <span class="news-meta-item">📥 ${item.scraped_at || ''}</span>
                    </div>
                </div>
            </div>
        </article>`;
    }
    container.innerHTML = html;
}

function renderTopNews(items) {
    const container = document.getElementById('topNewsFeed');

    if (!items || items.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-secondary);">No top news available</p>';
        return;
    }

    let html = '';
    for (const item of items) {
        const src = item.source || 'Unknown';
        const srcDisplay = getDisplayName(src) || src || 'News Source';
        const timeAgo = computeTimeAgo(item);
        const url = item.news_url || '#';
        const title = item.news_caption || 'Untitled';
        const imageUrl = item.image_url || '';

        const thumbHtml = imageUrl
            ? `<div class="top-news-card-thumb">
                   <a href="${escapeHtml(url)}" target="_blank" rel="noopener">
                       <img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(srcDisplay)}" loading="lazy" onerror="this.parentElement.parentElement.style.display='none'">
                   </a>
               </div>`
            : '';

        html += `
        <article class="top-news-card ${imageUrl ? 'has-thumbnail' : ''}">
            ${thumbHtml}
            <div class="top-news-card-content">
                <div class="top-news-card-title">
                    <a href="${escapeHtml(url)}" target="_blank" rel="noopener" title="${escapeHtml(title)}">${escapeHtml(title)}</a>
                </div>
                <div class="top-news-card-meta">
                    <span class="top-news-source-badge source-${src.toLowerCase()}">${srcDisplay}</span>
                    <span class="meta-separator">•</span>
                    <span class="top-news-time">⏱ ${timeAgo}</span>
                </div>
            </div>
        </article>`;
    }
    container.innerHTML = html;
}

// ─── Filtering & Sorting ────────────────────────────────────────────

function getFilteredNews() {
    const query = document.getElementById('searchInput').value.trim();

    let items = [...allNews];

    // Source filter
    if (currentSource !== 'all') {
        items = items.filter(n => n.source === currentSource);
    }

    // Search - simple string matching
    if (query) {
        const queryLower = query.toLowerCase();
        items = items.filter(n => {
            const caption = (n.news_caption || '').toLowerCase();
            const summary = (n.news_summary || '').toLowerCase();
            const source = (n.source || '').toLowerCase();
            const url = (n.news_url || '').toLowerCase();
            return caption.includes(queryLower) ||
                   summary.includes(queryLower) ||
                   source.includes(queryLower) ||
                   url.includes(queryLower);
        });
    }

    return sortNews(items);
}

function sortNews(items) {
    switch (currentSort) {
        case 'newest':
            return items.sort((a, b) => newsTimestamp(b) - newsTimestamp(a));
        case 'oldest':
            return items.sort((a, b) => newsTimestamp(a) - newsTimestamp(b));
        case 'source':
            return items.sort((a, b) => (a.source || '').localeCompare(b.source || '') || newsTimestamp(b) - newsTimestamp(a));
        default:
            return items;
    }
}

function onFilterChange() {
    if (isTopNewsMode) {
        renderTopNews(topNews);
        return;
    }
    renderNews();
}

function setTopNewsMode(enabled) {
    isTopNewsMode = Boolean(enabled);

    const topSection = document.getElementById('topNewsSection');
    const mainFeed = document.getElementById('newsFeed');
    topSection.style.display = isTopNewsMode ? 'block' : 'none';
    mainFeed.style.display = isTopNewsMode ? 'none' : 'block';

    if (isTopNewsMode) {
        startTopNewsLiveUpdates();
        fetchTopNews({ renderIfVisible: true });
        renderTopNews(topNews);
    } else {
        stopTopNewsLiveUpdates();
        renderNews();
    }

    renderStats();
    renderSidebar();
}

function fingerprintTopNews(items) {
    if (!Array.isArray(items) || items.length === 0) return '';
    return items
        .slice(0, 100)
        .map(item => [
            item.id || '',
            item.news_url || '',
            item.news_caption || '',
            item.ranked_at || '',
            item.score || '',
            item.semantic_score || '',
        ].join('|'))
        .join('||');
}

// ─── Utilities ──────────────────────────────────────────────────────

function newsTimestamp(item) {
    const d = item.news_date || '';
    const t = (item.news_time || '').replace(' IST', '').trim();
    if (!d || !t) return 0;
    try {
        return new Date(`${d} ${t}`).getTime() || 0;
    } catch { return 0; }
}

function computeTimeAgo(item) {
    const ts = newsTimestamp(item);
    if (!ts) return item.time_ago || '';

    const now = new Date();
    const istNow = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
    const diff = Math.floor((istNow.getTime() - ts) / 1000);

    if (diff < 0) return 'just now';
    if (diff < 60) return diff < 10 ? 'just now' : `${diff} sec ago`;
    const min = Math.floor(diff / 60);
    if (min < 60) return `${min} min ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr} hr ago`;
    const days = Math.floor(hr / 24);
    return `${days} day${days !== 1 ? 's' : ''} ago`;
}

function formatUptime(seconds) {
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

function getDisplayName(sourceName) {
    if (!sourceName) return 'News Source';

    // Try exact match first
    let found = sources.find(s => s.name === sourceName);
    if (found) return found.display_name;

    // Try case-insensitive match
    const lower = sourceName.toLowerCase();
    found = sources.find(s => s.name.toLowerCase() === lower);
    if (found) return found.display_name;

    // Fallback: format the source name nicely (capitalize words)
    return sourceName
        .split(/[-_\s]+/)
        .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
        .join(' ');
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function debounce(fn, ms) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), ms);
    };
}
