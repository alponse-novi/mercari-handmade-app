import asyncio
import urllib3
import httpx

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# httpx SSL検証をスキップ (ローカル証明書の問題を回避)
_orig_httpx_init = httpx.AsyncClient.__init__
def _patched_httpx_init(self, *args, **kwargs):
    kwargs.setdefault("verify", False)
    _orig_httpx_init(self, *args, **kwargs)
httpx.AsyncClient.__init__ = _patched_httpx_init

import mercapi as _mercapi  # noqa: E402
from mercapi.requests import SearchRequestData  # noqa: E402

CATEGORIES = {
    "レザー": ["レザー ハンドメイド", "革 ハンドメイド"],
    "レジン": ["レジン ハンドメイド"],
    "ポーチ": ["ポーチ ハンドメイド"],
    "バッグ": ["バッグ ハンドメイド", "鞄 ハンドメイド"],
    "キーホルダー": ["キーホルダー ハンドメイド"],
    "ペット": ["ペット ハンドメイド", "犬 ハンドメイド", "猫 ハンドメイド"],
}

TARGET_ITEMS = 200


def _item_to_dict(item, status: str = "on_sale") -> dict | None:
    price = getattr(item, "price", 0) or 0
    item_id = getattr(item, "id_", "") or ""
    if not item_id:
        return None
    thumbnails = getattr(item, "thumbnails", []) or []
    return {
        "id": item_id,
        "name": getattr(item, "name", "") or "",
        "price": int(price) if price else 0,
        "image_url": thumbnails[0] if thumbnails else "",
        "url": f"https://jp.mercari.com/item/{item_id}",
        "status": status,
    }


async def _fetch_pages(results, limit: int) -> list:
    """ページネーションで最大 limit 件のアイテムを取得"""
    raw = list(results.items or [])
    if len(raw) >= 120 and len(raw) < limit:
        try:
            page2 = await results.next_page()
            raw.extend(page2.items or [])
        except Exception:
            pass
    return raw[:limit]


async def _fetch_on_sale(client: _mercapi.Mercapi, keyword: str) -> list[dict]:
    """出品中アイテム最大200件"""
    try:
        results = await client.search(keyword)
        raw = await _fetch_pages(results, TARGET_ITEMS)
        return [d for item in raw if (d := _item_to_dict(item, "on_sale"))]
    except Exception as e:
        print(f"[on_sale error] {keyword}: {e}")
        return []


async def _fetch_sold_items(client: _mercapi.Mercapi, keyword: str) -> list[dict]:
    """SOLD済みアイテム最大200件"""
    try:
        results = await client.search(
            keyword,
            status=[SearchRequestData.Status.STATUS_SOLD_OUT],
        )
        raw = await _fetch_pages(results, TARGET_ITEMS)
        return [d for item in raw if (d := _item_to_dict(item, "sold"))]
    except Exception as e:
        print(f"[sold error] {keyword}: {e}")
        return []


async def _fetch_category_async(category_name: str) -> dict:
    """
    Returns:
        {
            "items":      list[dict],  # 出品中アイテム (max 200件)
            "sold_items": list[dict],  # SOLD済みアイテム (max 200件) ← キーワード分析用
        }
    """
    keywords = CATEGORIES.get(category_name, [])
    client = _mercapi.Mercapi()

    seen_on_sale: set[str] = set()
    seen_sold: set[str] = set()
    all_items: list[dict] = []
    all_sold: list[dict] = []

    for i, kw in enumerate(keywords):
        if i > 0:
            await asyncio.sleep(2.0)

        # 出品中 と SOLD を並列取得
        on_sale_items, sold_items = await asyncio.gather(
            _fetch_on_sale(client, kw),
            _fetch_sold_items(client, kw),
        )

        for item in on_sale_items:
            if item["id"] not in seen_on_sale:
                seen_on_sale.add(item["id"])
                item["category"] = category_name
                all_items.append(item)

        for item in sold_items:
            if item["id"] not in seen_sold:
                seen_sold.add(item["id"])
                item["category"] = category_name
                all_sold.append(item)

    return {
        "items": all_items,
        "sold_items": all_sold,
    }


def fetch_category(category_name: str) -> dict:
    return asyncio.run(_fetch_category_async(category_name))
