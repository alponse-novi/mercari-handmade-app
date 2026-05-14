import re
import time
import subprocess
import sys

CATEGORIES = {
    "レザー": ["レザー ハンドメイド", "革 ハンドメイド"],
    "レジン": ["レジン ハンドメイド"],
    "ポーチ": ["ポーチ ハンドメイド"],
    "バッグ": ["バッグ ハンドメイド"],
    "キーホルダー": ["キーホルダー ハンドメイド"],
    "ペット": ["ペット ハンドメイド"],
    "財布": ["財布 ハンドメイド", "ウォレット ハンドメイド"],
    "パスケース": ["パスケース ハンドメイド", "カードケース ハンドメイド"],
    "キーケース": ["キーケース ハンドメイド"],
    "羊毛フェルト": ["羊毛フェルト ハンドメイド"],
}

BASE_URL = "https://www.creema.jp"
LISTING_URL = f"{BASE_URL}/listing"
TARGET_ITEMS = 200
MAX_PAGES = 2  # 1ページ約160件 × 2 = 320件超
PAGE_WAIT_SEC = 1.5

_BROWSER_INSTALLED = False


def _ensure_browser():
    global _BROWSER_INSTALLED
    if _BROWSER_INSTALLED:
        return
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, check=False, timeout=120,
        )
    except Exception:
        pass
    _BROWSER_INSTALLED = True


def _launch_browser(pw):
    return pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--no-zygote",
            "--disable-gpu",
            "--single-process",
        ],
    )


# JavaScript to extract product cards from Creema listing page
_EXTRACT_JS = """
() => {
    const articles = Array.from(document.querySelectorAll('article.c-item-article[data-id]'));
    const seen = new Set();
    return articles.filter(a => {
        const id = a.getAttribute('data-id');
        if (!id || seen.has(id)) return false;
        seen.add(id);
        return true;
    }).map(a => {
        const img = a.querySelector('img');
        const link = a.querySelector('a[href*="/item/"]');
        const id = a.getAttribute('data-id');
        const priceRaw = a.getAttribute('data-display-price') || '';
        return {
            id: id || '',
            name: img ? img.alt : '',
            price: parseInt(priceRaw) || 0,
            image_url: img ? img.src : '',
            url: 'https://www.creema.jp/item/' + id + '/detail',
        };
    });
}
"""


def _scrape_page(page, keyword: str, page_num: int) -> list[dict]:
    params = f"mode=keyword&q={keyword.replace(' ', '+')}&page={page_num}"
    url = f"{LISTING_URL}?{params}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(PAGE_WAIT_SEC)
        items = page.evaluate(_EXTRACT_JS)
        return items or []
    except Exception as e:
        print(f"[creema error] keyword={keyword} page={page_num}: {e}")
        return []


def fetch_category(category_name: str) -> dict:
    _ensure_browser()
    keywords = CATEGORIES.get(category_name, [])

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[creema] playwright not installed")
        return {"items": [], "sold_items": []}

    seen: set[str] = set()
    all_items: list[dict] = []

    with sync_playwright() as pw:
        browser = _launch_browser(pw)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = ctx.new_page()

        for kw_idx, kw in enumerate(keywords):
            if kw_idx > 0:
                time.sleep(2.0)
            for pg_num in range(1, MAX_PAGES + 1):
                if len(all_items) >= TARGET_ITEMS:
                    break
                raw = _scrape_page(page, kw, pg_num)
                if not raw:
                    break
                for item in raw:
                    if item["id"] and item["id"] not in seen:
                        seen.add(item["id"])
                        item["category"] = category_name
                        item["status"] = "on_sale"
                        all_items.append(item)
                time.sleep(PAGE_WAIT_SEC)

        browser.close()

    return {
        "items": all_items[:TARGET_ITEMS],
        "sold_items": [],
    }


def search_keyword(keyword: str, limit: int = 100) -> dict:
    """任意キーワードで検索して出品中アイテムを返す"""
    _ensure_browser()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"items": [], "sold_items": []}

    items = []
    seen: set[str] = set()
    with sync_playwright() as pw:
        browser = _launch_browser(pw)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = ctx.new_page()
        for pg in range(1, 3):
            raw = _scrape_page(page, keyword, pg)
            if not raw:
                break
            for item in raw:
                if item["id"] and item["id"] not in seen:
                    seen.add(item["id"])
                    item["category"] = keyword
                    item["status"] = "on_sale"
                    items.append(item)
            time.sleep(PAGE_WAIT_SEC)
            if len(items) >= limit:
                break
        browser.close()
    return {"items": items[:limit], "sold_items": []}


def fetch_all_genre_counts(genre_keywords: dict, progress_callback=None) -> dict:
    """ブラウザ1つで全ジャンルの出品数（1ページ分）を取得して返す"""
    _ensure_browser()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {}

    results = {}
    total = len(genre_keywords)

    with sync_playwright() as pw:
        browser = _launch_browser(pw)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = ctx.new_page()
        for i, (genre, keyword) in enumerate(genre_keywords.items()):
            items = _scrape_page(page, keyword, 1)
            results[genre] = len(items)
            if progress_callback:
                progress_callback((i + 1) / total, genre)
            time.sleep(PAGE_WAIT_SEC)
        browser.close()

    return results
