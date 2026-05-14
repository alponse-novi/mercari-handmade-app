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
}

BASE_URL = "https://minne.com"
SEARCH_URL = f"{BASE_URL}/category/saleonly"
TARGET_ITEMS = 200
MAX_PAGES = 5
PAGE_WAIT_SEC = 2.0

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


# JavaScript to extract product cards from Minne search page
_EXTRACT_JS = """
() => {
    const seen = new Set();
    const results = [];
    const links = Array.from(document.querySelectorAll('a')).filter(l => {
        const href = l.href || '';
        return href.match(/minne\\.com\\/items\\/\\d+/);
    });
    for (const link of links) {
        const m = (link.href || '').match(/\\/items\\/(\\d+)/);
        if (!m || seen.has(m[1])) continue;
        seen.add(m[1]);

        // Walk up to find the card container with an image
        let card = link.parentElement;
        let img = null;
        for (let i = 0; i < 8 && card; i++) {
            img = card.querySelector('img[src*="image.minne.com"]');
            if (img) break;
            card = card.parentElement;
        }
        if (!img) continue;

        // Price element
        let priceText = '';
        if (card) {
            const priceEl = card.querySelector(
                '[class*="Price_price"], [class*="price"], [class*="Price"]'
            );
            if (priceEl) priceText = priceEl.textContent.trim();
        }

        results.push({
            id: m[1],
            name: img.alt || '',
            image_url: img.src || '',
            url: 'https://minne.com/items/' + m[1],
            price_text: priceText,
        });
    }
    return results;
}
"""


def _parse_price(price_text: str) -> int:
    digits = re.sub(r"[^\d]", "", price_text)
    return int(digits) if digits else 0


def _scrape_page(page, keyword: str, page_num: int) -> list[dict]:
    params = f"q={keyword.replace(' ', '+')}&page={page_num}"
    url = f"{SEARCH_URL}?{params}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(PAGE_WAIT_SEC)
        raw = page.evaluate(_EXTRACT_JS)
        items = []
        for r in (raw or []):
            items.append({
                "id": r["id"],
                "name": r["name"],
                "price": _parse_price(r.get("price_text", "")),
                "image_url": r["image_url"],
                "url": r["url"],
            })
        return items
    except Exception as e:
        print(f"[minne error] keyword={keyword} page={page_num}: {e}")
        return []


def fetch_category(category_name: str) -> dict:
    _ensure_browser()
    keywords = CATEGORIES.get(category_name, [])

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[minne] playwright not installed")
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
                items = _scrape_page(page, kw, pg_num)
                if not items:
                    break
                for item in items:
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
