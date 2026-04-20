/* ── State ── */
let allArticles = [];
let currentFilter = 'all';

/* ── Category Config ── */
const CAT = {
  tw_stocks: { label: '台股',  emoji: '🇹🇼', cls: 'badge-tw'     },
  us_stocks: { label: '美股',  emoji: '🇺🇸', cls: 'badge-us'     },
  crypto:    { label: '幣圈',  emoji: '🪙',  cls: 'badge-crypto' },
  startup:   { label: '新創',  emoji: '🚀',  cls: 'badge-startup'},
};

const SENTIMENT = {
  positive: { label: '偏多', cls: 'badge-positive' },
  negative: { label: '偏空', cls: 'badge-negative' },
  neutral:  { label: '中性', cls: 'badge-neutral'  },
};

const IMPACT = {
  high:   { label: '高影響', cls: 'badge-impact-high'   },
  medium: { label: '中影響', cls: 'badge-impact-medium' },
  low:    { label: '低影響', cls: 'badge-impact-low'    },
};

/* ── Load Data ── */
async function loadData() {
  try {
    const res  = await fetch(`data/latest.json?t=${Date.now()}`);
    const data = await res.json();
    renderAll(data);
  } catch (e) {
    document.getElementById('hero-summary').textContent = '資料載入失敗，請稍後再試。';
    console.error(e);
  }
}

/* ── Render Everything ── */
function renderAll(data) {
  renderHero(data.market_sentiment, data.key_prices, data.updated_at);
  allArticles = data.articles || [];
  renderGrid();
}

/* ── Hero ── */
function renderHero(sentiment, prices, updatedAt) {
  const score = sentiment?.score ?? 50;
  const label = sentiment?.label ?? '中性';
  const summary = sentiment?.summary ?? '—';

  // 情緒分類
  let moodCls = 'neutral';
  if (score >= 60) moodCls = 'bull';
  if (score <= 40) moodCls = 'bear';

  const pulse = document.getElementById('hero-pulse');
  pulse.className = `hero-pulse ${moodCls}`;
  document.getElementById('pulse-score').textContent = score;

  document.getElementById('hero-sentiment-label').textContent = label;
  document.getElementById('hero-summary').textContent = summary;

  // 幣價
  const priceEl = document.getElementById('hero-prices');
  if (prices && Object.keys(prices).length) {
    priceEl.innerHTML = Object.entries(prices).map(([sym, d]) => {
      const up = d.change >= 0;
      return `
        <div class="price-card">
          <div class="sym">${sym}</div>
          <div class="val">$${formatPrice(d.price)}</div>
          <div class="chg ${up ? 'up' : 'down'}">${up ? '+' : ''}${d.change.toFixed(2)}%</div>
        </div>`;
    }).join('');
  }

  // 更新時間
  if (updatedAt) {
    const dt = new Date(updatedAt);
    document.getElementById('updated-at').textContent =
      dt.toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
  }
}

/* ── News Grid ── */
function renderGrid() {
  const grid  = document.getElementById('news-grid');
  const empty = document.getElementById('empty-state');

  const filtered = currentFilter === 'all'
    ? allArticles
    : allArticles.filter(a => a.category === currentFilter);

  if (!filtered.length) {
    grid.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';

  grid.innerHTML = filtered.map(article => buildCard(article)).join('');
}

function buildCard(a) {
  const cat  = CAT[a.category]   || { label: a.category, emoji: '📰', cls: '' };
  const sent = SENTIMENT[a.claude_sentiment] || SENTIMENT.neutral;
  const imp  = IMPACT[a.claude_impact]       || IMPACT.low;

  const time = relativeTime(a.published_at);

  const assetsHtml = (a.claude_affected_assets || []).length
    ? `<div class="card-assets">${a.claude_affected_assets.map(t =>
        `<span class="asset-tag">${escHtml(t)}</span>`).join('')}</div>`
    : '';

  const takeaway = a.claude_takeaway && a.claude_takeaway !== '—'
    ? `<div class="card-takeaway">${escHtml(a.claude_takeaway)}</div>`
    : '';

  const summary = a.claude_summary && a.claude_summary !== '—'
    ? `<p class="card-summary">${escHtml(a.claude_summary)}</p>`
    : '';

  return `
    <article class="news-card">
      <div class="card-top">
        <div class="card-badges">
          <span class="badge ${cat.cls}">${cat.emoji} ${cat.label}</span>
          <span class="badge ${sent.cls}">${sent.label}</span>
          ${imp.cls !== 'badge-impact-low' ? `<span class="badge ${imp.cls}">${imp.label}</span>` : ''}
        </div>
        <span class="card-time">${time}</span>
      </div>

      <h3 class="card-title">
        <a href="${escHtml(a.url)}" target="_blank" rel="noopener">${escHtml(a.title)}</a>
      </h3>

      ${summary}
      ${takeaway}
      ${assetsHtml}

      <p class="card-source">${escHtml(a.source)}</p>
    </article>`;
}

/* ── Filter ── */
function setFilter(cat) {
  currentFilter = cat;
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.cat === cat);
  });
  renderGrid();
}

/* ── Utils ── */
function formatPrice(p) {
  if (p >= 10000) return p.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (p >= 100)   return p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (p >= 1)     return p.toFixed(3);
  return p.toFixed(4);
}

function relativeTime(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return '剛剛';
  if (m < 60) return `${m} 分鐘前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小時前`;
  return `${Math.floor(h / 24)} 天前`;
}

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ── Init ── */
loadData();

// 每 10 分鐘自動刷新
setInterval(loadData, 10 * 60 * 1000);
