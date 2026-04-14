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
const TOP_NEWS_REFRESH_INTERVAL = 2_000;
const CLOCK_INTERVAL = 1_000;

let allNews = [];
let topNews = [];
let fuseInstance = null;
let currentSource = 'all';
let currentSort = 'newest';
let currentCategory = 'all';
let isTopNewsMode = false;
let sources = [];
let statsData = {};
let topNewsRefreshTimer = null;
let topNewsFingerprint = '';

const STRICT_CATEGORIES = ['business', 'markets', 'politics', 'india', 'world', 'others'];
const CATEGORY_LABELS = {
    all: 'Latest',
    business: 'Business',
    markets: 'Markets',
    politics: 'Politics',
    india: 'India',
    world: 'World',
    others: 'Others',
};
const CATEGORY_TABS = ['all', ...STRICT_CATEGORIES];

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
    initCategoryTabs();
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
        onFilterChange();
    });

    const allSourcesBtn = document.getElementById('allSourcesBtn');
    const topNewsBtn = document.getElementById('topNewsBtn');

    if (allSourcesBtn) {
        allSourcesBtn.addEventListener('click', () => {
            currentSource = 'all';
            setTopNewsMode(false);
            renderSidebar();
            fetchNews();
        });
    }

    if (topNewsBtn) {
        topNewsBtn.addEventListener('click', () => {
            setTopNewsMode(true);
        });
    }
}

function initCategoryTabs() {
    renderCategoryTabs();
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
        fetchSources(),
        fetchStats(),
        fetchNews(),
        fetchTopNews({ renderIfVisible: isTopNewsMode }),
    ]);
    renderSidebar();
}

async function fetchSources() {
    try {
        const resp = await fetch(`${API_BASE}/api/sources`);
        sources = await resp.json();
        document.getElementById('sourceCount').textContent = sources.filter(s => s.enabled).length;
        document.getElementById('sidebarSourceCount').textContent = sources.filter(s => s.enabled).length;
    } catch (e) { console.error('Failed to fetch sources:', e); }
}

async function fetchStats() {
    try {
        const resp = await fetch(`${API_BASE}/api/stats`);
        statsData = await resp.json();
        renderStats();
    } catch (e) { console.error('Failed to fetch stats:', e); }
}

async function fetchNews() {
    const date = document.getElementById('dateFilter').value;
    const sourceParam = currentSource !== 'all' ? `&source=${currentSource}` : '';
    try {
        const resp = await fetch(`${API_BASE}/api/news?date=${date}&limit=1000${sourceParam}`);
        allNews = await resp.json();
        buildFuseIndex();
        renderCategoryTabs();
        const loadingEl = document.getElementById('loading');
        if (loadingEl) loadingEl.style.display = 'none';
        if (!isTopNewsMode) {
            renderNews();
        }
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
        topNews = await resp.json();
        renderCategoryTabs();

        const nextFingerprint = fingerprintTopNews(topNews);
        const changed = nextFingerprint !== topNewsFingerprint;
        topNewsFingerprint = nextFingerprint;

        if (renderIfVisible && isTopNewsMode && changed) {
            renderTopNews();
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
        <div class="sidebar-source-card ${!isTopNewsMode && currentSource === 'all' ? 'active' : ''}" data-source="all">
            <div class="sidebar-source-header">
                <span class="sidebar-source-name">🌐 All Sources</span>
            </div>
        </div>
    `;

    for (const src of sources) {
        if (!src.enabled) continue;
        if (filterText && !src.display_name.toLowerCase().includes(filterText) && !src.name.includes(filterText)) continue;

        const w = workers[src.name] || {};
        const st = srcStats[src.name] || {};
        const isActive = !isTopNewsMode && currentSource === src.name;
        const status = w.status || 'unknown';
        const sourceUrl = SOURCE_LINKS[src.name] || '';
        const sourceNameHtml = sourceUrl
            ? `<a class="sidebar-source-name sidebar-source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(src.display_name)}</a>`
            : `<span class="sidebar-source-name">${escapeHtml(src.display_name)}</span>`;

        let errorHtml = '';
        if (w.last_error) {
            const errorTime = w.last_error_time ? new Date(w.last_error_time * 1000).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' }) : '?';
            errorHtml = `<div class="sidebar-source-error">⚠ ${escapeHtml(w.last_error.substring(0, 80))} (${errorTime})</div>`;
        }

        let emptyHtml = '';
        // if (w.consecutive_empty && w.consecutive_empty >= 10) {
        //     emptyHtml = `<div class="sidebar-source-error">⏳ No data for ${w.consecutive_empty} fetches</div>`;
        // }

        html += `
        <div class="sidebar-source-card ${isActive ? 'active' : ''}" data-source="${src.name}">
            <div class="sidebar-source-header">
                ${sourceNameHtml}
                <span class="health-status ${status}">${status}</span>
            </div>
            <div class="sidebar-source-stats">
                <span>Total: ${(st.total_articles || 0).toLocaleString()}</span>
                <span>Today: ${(st.today_articles || 0).toLocaleString()}</span>
            </div>
            <div class="sidebar-source-detail">
                <span>Poll: ${w.poll_interval ? w.poll_interval[0] + '-' + w.poll_interval[1] + 's' : '?'}</span>
                <span>Errors: ${w.consecutive_errors || 0}</span>
            </div>
            ${w.is_blocked ? '<div class="sidebar-source-blocked">⚠ BLOCKED</div>' : ''}
            ${errorHtml}
            ${emptyHtml}
            <div class="sidebar-source-desc">${escapeHtml(src.description || '')}</div>
        </div>`;
    }

    container.innerHTML = html;

    // Click handlers
    container.querySelectorAll('.sidebar-source-card').forEach(card => {
        card.addEventListener('click', () => {
            currentSource = card.dataset.source;
            setTopNewsMode(false);
            renderSidebar();
            fetchNews();
        });
    });

    container.querySelectorAll('.sidebar-source-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.stopPropagation();
        });
    });
}

function renderSourceTabs() {
    // Legacy: no-op, superseded by sidebar
}

function renderCategoryTabs() {
    const container = document.getElementById('categoryTabs');
    if (!container) return;

    const counts = getCategoryCounts();
    container.innerHTML = CATEGORY_TABS.map((cat) => {
        const label = CATEGORY_LABELS[cat] || cat;
        const count = counts[cat] || 0;
        const active = currentCategory === cat ? 'active' : '';
        return `<button class="category-tab ${active}" type="button" data-category="${cat}">${escapeHtml(label)} <span class="category-tab-count">(${count})</span></button>`;
    }).join('');

    container.querySelectorAll('.category-tab').forEach((button) => {
        button.addEventListener('click', () => {
            const category = button.dataset.category || 'all';
            currentCategory = category;
            renderCategoryTabs();
            onFilterChange();
        });
    });
}

function getCategoryCounts() {
    const counts = { all: 0, business: 0, markets: 0, politics: 0, india: 0, world: 0, others: 0 };
    const base = isTopNewsMode
        ? [...topNews]
        : (currentSource === 'all' ? [...allNews] : allNews.filter(item => item.source === currentSource));

    counts.all = base.length;
    for (const item of base) {
        for (const cat of getItemCategories(item)) {
            if (cat in counts) {
                counts[cat] += 1;
            }
        }
    }

    return counts;
}

function normalizeCategory(category) {
    const val = String(category || '').trim().toLowerCase();
    if (val === 'other') return 'others';
    return STRICT_CATEGORIES.includes(val) ? val : '';
}

function getItemCategories(item) {
    const raw = Array.isArray(item.categories)
        ? item.categories
        : (item.category ? [item.category] : []);

    const cleaned = [];
    for (const cat of raw) {
        const normalized = normalizeCategory(cat);
        if (normalized && !cleaned.includes(normalized)) {
            cleaned.push(normalized);
        }
        if (cleaned.length >= 3) break;
    }

    return cleaned.length > 0 ? cleaned : ['others'];
}

function matchesCurrentCategory(item) {
    if (currentCategory === 'all') return true;
    return getItemCategories(item).includes(currentCategory);
}

function renderCategoryChips(item, wrapperClass) {
    const cats = getItemCategories(item);
    if (!cats.length) return '';
    const chips = cats.map((cat) => {
        const label = CATEGORY_LABELS[cat] || cat;
        return `<span class="category-chip ${cat}">${escapeHtml(label)}</span>`;
    }).join('');
    return `<div class="${wrapperClass}">${chips}</div>`;
}

function renderStats() {
    if (!statsData) return;

    document.getElementById('totalArticles').textContent = (statsData.total_articles || 0).toLocaleString();

    let todayTotal = 0;
    const srcStats = statsData.sources || {};
    for (const key in srcStats) {
        todayTotal += srcStats[key].today_articles || 0;
    }
    document.getElementById('todayArticles').textContent = todayTotal.toLocaleString();

    const workers = statsData.workers || {};
    const activeCount = Object.values(workers).filter(w => w.status === 'healthy').length;
    const totalSources = Object.keys(workers).length;
    document.getElementById('activeSources').textContent = `${activeCount}/${totalSources}`;

    if (statsData.uptime_seconds) {
        document.getElementById('uptime').textContent = formatUptime(statsData.uptime_seconds);
    }

    const now = new Date();
    const istStr = now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' });
    document.getElementById('lastUpdated').textContent = istStr;
}

function renderHealthCards() {
    // Legacy: no-op, superseded by sidebar
}

function renderNews() {
    if (isTopNewsMode) return;

    const container = document.getElementById('newsFeed');
    let items = getFilteredNews();

    // Sort
    items = sortNews(items);

    if (items.length === 0) {
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
        const categoriesHtml = renderCategoryChips(item, 'news-categories');

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
                    ${categoriesHtml}
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

function renderTopNews() {
    const container = document.getElementById('topNewsFeed');
    if (!container) return;

    let items = getFilteredTopNews();
    items = sortNews(items);

    if (items.length === 0) {
        container.innerHTML = '<div class="no-results">No top news articles found.</div>';
        return;
    }

    let html = '';
    for (const item of items) {
        const srcClass = (item.source || '').toLowerCase();
        const sourceLabel = getDisplayName(item.source || '');
        const title = item.news_caption || 'Untitled';
        const url = item.news_url || '#';
        const imageUrl = item.image_url || '';
        const timeAgo = computeTimeAgo(item);
        const categoriesHtml = renderCategoryChips(item, 'top-news-categories');

        const imageHtml = imageUrl
            ? `<div class="top-news-card-thumb"><a href="${escapeHtml(url)}" target="_blank" rel="noopener"><img src="${escapeHtml(imageUrl)}" alt="" loading="lazy" onerror="this.parentElement.parentElement.style.display='none'"></a></div>`
            : '';

        html += `
        <article class="top-news-card">
            ${imageHtml}
            <div class="top-news-card-content">
                <div class="top-news-card-title"><a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(title)}</a></div>
                ${categoriesHtml}
                <div class="top-news-card-meta">
                    <span class="top-news-source-badge source-${srcClass}">${escapeHtml(sourceLabel)}</span>
                    <span class="meta-separator">•</span>
                    <span>⏱ ${timeAgo}</span>
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

    // Source filter (already applied in API call, but double-check)
    if (currentSource !== 'all') {
        items = items.filter(n => n.source === currentSource);
    }

    items = items.filter(matchesCurrentCategory);

    // Search
    if (query && fuseInstance) {
        const results = fuseInstance.search(query);
        items = results.map(r => r.item);
        // If source filtered
        if (currentSource !== 'all') {
            items = items.filter(n => n.source === currentSource);
        }
        items = items.filter(matchesCurrentCategory);
    }

    return items;
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
    renderCategoryTabs();
    if (isTopNewsMode) {
        renderTopNews();
        return;
    }
    renderNews();
}

function setTopNewsMode(enabled) {
    isTopNewsMode = Boolean(enabled);

    const topSection = document.getElementById('topNewsSection');
    const newsFeed = document.getElementById('newsFeed');

    if (topSection) topSection.style.display = isTopNewsMode ? 'block' : 'none';
    if (newsFeed) newsFeed.style.display = isTopNewsMode ? 'none' : 'block';

    if (isTopNewsMode) {
        currentSource = 'all';
        startTopNewsLiveUpdates();
        fetchTopNews({ renderIfVisible: true });
        renderTopNews();
    } else {
        stopTopNewsLiveUpdates();
        renderNews();
    }

    renderSidebar();
    renderCategoryTabs();
    renderStats();
    renderModeButtons();
}

function renderModeButtons() {
    const allSourcesBtn = document.getElementById('allSourcesBtn');
    const topNewsBtn = document.getElementById('topNewsBtn');

    if (allSourcesBtn) {
        allSourcesBtn.classList.toggle('active', !isTopNewsMode && currentSource === 'all');
    }

    if (topNewsBtn) {
        topNewsBtn.classList.toggle('active', isTopNewsMode);
    }
}

function getFilteredTopNews() {
    const query = document.getElementById('searchInput').value.trim().toLowerCase();
    let items = [...topNews];

    items = items.filter(matchesCurrentCategory);

    if (!query) return items;

    return items.filter(item => {
        const caption = (item.news_caption || '').toLowerCase();
        const summary = (item.news_summary || '').toLowerCase();
        const source = (item.source || '').toLowerCase();
        const url = (item.news_url || '').toLowerCase();
        return caption.includes(query) || summary.includes(query) || source.includes(query) || url.includes(query);
    });
}

function fingerprintTopNews(items) {
    if (!Array.isArray(items) || items.length === 0) return '';
    return items
        .slice(0, 100)
        .map(item => [item.news_url || '', item.news_caption || '', item.scraped_at || ''].join('|'))
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
    const found = sources.find(s => s.name === sourceName);
    return found ? found.display_name : sourceName || 'Unknown';
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
