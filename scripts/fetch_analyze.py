"""
Phili Market Intelligence — 資料抓取與 Claude 分析腳本
每 6 小時由 GitHub Actions 執行，產出 data/latest.json
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import anthropic

# ── 設定 ─────────────────────────────────────────────────────────────

TAIPEI = timezone(timedelta(hours=8))
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "latest.json")

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# 新聞來源（RSS feeds，不需要任何 API key）
RSS_FEEDS = {
    "us_stocks": [
        "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.reuters.com/reuters/technologyNews",
    ],
    "crypto": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
    ],
    "tw_stocks": [
        "https://technews.tw/feed/",
        "https://www.inside.com.tw/feed",
    ],
    "startup": [
        "https://techcrunch.com/feed/",
        "https://vcnewsdaily.com/feed/",
    ],
}

# 與自選股相關的關鍵字（用於篩選相關新聞）
WATCHLIST_KEYWORDS = [
    # 台股
    "TSMC", "台積電", "聯電", "長榮", "緯創", "緯穎", "元太", "華碩", "廣達",
    "台達電", "聯發科", "技嘉", "鴻海", "富邦", "兆豐", "中信金",
    # 美股
    "NVDA", "nvidia", "MSTR", "MicroStrategy", "META", "Google", "Amazon",
    "Microsoft", "Apple", "Tesla", "TSLA", "S&P", "Nasdaq", "VIX",
    # 幣圈
    "Bitcoin", "BTC", "Ethereum", "ETH", "Solana", "SOL", "Cardano", "ADA", "Dogecoin", "DOGE",
    "crypto", "blockchain", "DeFi", "ETF", "spot ETF",
    # 新創 / 總經
    "startup", "venture", "VC", "funding", "IPO", "Fed", "interest rate", "inflation",
    "Taiwan", "semiconductor", "AI", "artificial intelligence",
]


# ── RSS 抓取 ──────────────────────────────────────────────────────────

def fetch_rss(url: str, category: str, max_age_hours: int = 18) -> list[dict]:
    """抓取單一 RSS feed，回傳最近 N 小時內的文章"""
    articles = []
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PhiliMarketBot/1.0)",
        "Accept": "application/rss+xml, application/xml, text/xml",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
        root = ET.fromstring(content)
    except Exception as e:
        print(f"[RSS] 抓取失敗 {url}: {e}")
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    for item in channel.findall("item"):
        try:
            title   = (item.findtext("title") or "").strip()
            link    = (item.findtext("link")  or "").strip()
            pub_raw = item.findtext("pubDate") or ""
            desc    = (item.findtext("description") or "").strip()

            # 去除 HTML tag
            import re
            desc = re.sub(r"<[^>]+>", "", desc)[:300]

            # 解析發布時間
            try:
                pub_dt = parsedate_to_datetime(pub_raw)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pub_dt = datetime.now(timezone.utc)

            if pub_dt < cutoff:
                continue

            # 篩選相關關鍵字
            text_lower = (title + " " + desc).lower()
            relevant = any(kw.lower() in text_lower for kw in WATCHLIST_KEYWORDS)
            if not relevant and category not in ("tw_stocks", "crypto"):
                # 台股與幣圈類的 feed 本身就是相關的，不需要關鍵字篩選
                continue

            articles.append({
                "title":       title,
                "url":         link,
                "source":      url.split("/")[2].replace("www.", "").replace("feeds.", ""),
                "category":    category,
                "published_at": pub_dt.astimezone(TAIPEI).isoformat(),
                "description": desc,
            })
        except Exception:
            continue

    return articles


def collect_all_news(limit: int = 25) -> list[dict]:
    """從所有 RSS feeds 抓新聞，去重後取最新的 limit 篇"""
    all_articles = []
    seen_titles  = set()

    for category, urls in RSS_FEEDS.items():
        for url in urls:
            arts = fetch_rss(url, category)
            for a in arts:
                key = a["title"].lower()[:60]
                if key not in seen_titles:
                    seen_titles.add(key)
                    all_articles.append(a)
            time.sleep(0.5)  # 避免請求太頻繁

    # 按時間排序，取最新的
    all_articles.sort(key=lambda x: x["published_at"], reverse=True)
    return all_articles[:limit]


# ── Claude 分析 ───────────────────────────────────────────────────────

ANALYSIS_PROMPT = """你是一位專業的財經分析師。以下是今天抓到的財經新聞列表（JSON格式）。

請對每篇文章進行分析，並以下面的 JSON 格式回傳結果：

{
  "market_sentiment": {
    "score": <0-100整數，0=極度悲觀，50=中性，100=極度樂觀>,
    "label": <"極度悲觀"|"偏空"|"中性"|"偏多"|"極度樂觀">,
    "summary": <一句話總結今日市場氛圍，繁體中文，30字以內>
  },
  "articles": [
    {
      "id": <文章索引，從0開始>,
      "summary": <2-3句核心摘要，繁體中文，聚焦對投資人重要的資訊>,
      "sentiment": <"positive"|"neutral"|"negative">,
      "impact": <"high"|"medium"|"low">,
      "affected_assets": <受影響的代號陣列，例如["NVDA","BTC","台積電"]，最多4個>,
      "takeaway": <一句話投資觀察，繁體中文，不超過25字>
    }
  ]
}

注意：
- 繁體中文，語氣簡潔專業
- affected_assets 只列與 Phili 自選清單相關的標的
- 自選清單：台積電、聯電、長榮、緯創、緯穎、元太、華碩、廣達、台達電、聯發科、技嘉、鴻海、富邦金、NVDA、MSTR、META、GOOG、AMZN、MSFT、AAPL、TSLA、SPY、QQQ、BTC、ETH、SOL、ADA、DOGE
- impact=high：Fed、重大財報、市場崩跌/急漲；medium：產業動態；low：一般資訊

以下是新聞列表：
"""


def analyze_with_claude(articles: list[dict]) -> dict:
    """用一次 Claude API 呼叫分析所有文章，回傳結構化結果"""
    if not ANTHROPIC_KEY:
        print("[Claude] 沒有 API key，跳過分析")
        return _empty_analysis(len(articles))

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    # 只傳必要欄位給 Claude，省 token
    slim = [
        {"id": i, "title": a["title"], "description": a["description"], "category": a["category"]}
        for i, a in enumerate(articles)
    ]

    prompt = ANALYSIS_PROMPT + json.dumps(slim, ensure_ascii=False, indent=2)

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()

        # 找到 JSON 區塊
        import re
        match = re.search(r"\{[\s\S]+\}", text)
        if not match:
            raise ValueError("Claude 回傳格式錯誤")

        result = json.loads(match.group())
        return result

    except Exception as e:
        print(f"[Claude] 分析失敗：{e}")
        return _empty_analysis(len(articles))


def _empty_analysis(n: int) -> dict:
    """當 Claude 分析失敗時的 fallback"""
    return {
        "market_sentiment": {"score": 50, "label": "中性", "summary": "資料更新中，請稍後再試"},
        "articles": [
            {"id": i, "summary": "—", "sentiment": "neutral",
             "impact": "low", "affected_assets": [], "takeaway": "—"}
            for i in range(n)
        ],
    }


# ── 價格資料 ──────────────────────────────────────────────────────────

def fetch_key_prices() -> dict:
    """抓主要資產的即時價格作為頁面輔助資訊"""
    import json as _json

    prices = {}

    # 幣圈（CoinGecko 免費）
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true"
        req = urllib.request.Request(url, headers={"User-Agent": "PhiliBot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = _json.loads(r.read())
        for cg_id, sym in [("bitcoin", "BTC"), ("ethereum", "ETH"), ("solana", "SOL")]:
            if cg_id in data:
                prices[sym] = {
                    "price":  data[cg_id]["usd"],
                    "change": round(data[cg_id].get("usd_24h_change", 0), 2),
                }
    except Exception as e:
        print(f"[Price] 幣圈資料失敗：{e}")

    return prices


# ── 主流程 ───────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now(TAIPEI).strftime('%Y-%m-%d %H:%M')} TST] 開始更新…")

    # 1. 抓新聞
    print("[1/3] 抓取新聞…")
    articles = collect_all_news(limit=20)
    print(f"      取得 {len(articles)} 篇文章")

    if not articles:
        print("[!] 沒有抓到任何文章，退出")
        sys.exit(0)

    # 2. Claude 分析
    print("[2/3] Claude 分析中…")
    analysis = analyze_with_claude(articles)

    # 3. 合併資料
    print("[3/3] 合併並寫入 JSON…")
    analyzed_map = {a["id"]: a for a in analysis.get("articles", [])}

    enriched = []
    for i, article in enumerate(articles):
        meta = analyzed_map.get(i, {})
        enriched.append({
            **article,
            "claude_summary":        meta.get("summary", "—"),
            "claude_sentiment":      meta.get("sentiment", "neutral"),
            "claude_impact":         meta.get("impact", "low"),
            "claude_affected_assets": meta.get("affected_assets", []),
            "claude_takeaway":       meta.get("takeaway", "—"),
        })

    # 抓幣價
    prices = fetch_key_prices()

    output = {
        "updated_at":       datetime.now(TAIPEI).isoformat(),
        "market_sentiment": analysis.get("market_sentiment", {}),
        "key_prices":       prices,
        "articles":         enriched,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[完成] 寫入 {OUTPUT_PATH}，共 {len(enriched)} 篇文章")


if __name__ == "__main__":
    main()
