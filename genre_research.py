import asyncio
import json
import time
from pathlib import Path

import cache_manager
import creema_client
import minne_client
import mercari_client as _mc  # noqa: F401 — apply httpx patches before mercapi import

import mercapi as _mercapi
from mercapi.requests import SearchRequestData

GENRE_CACHE_TTL = 60 * 60 * 12  # 12時間

CACHE_KEYS = {
    "mercari": "genre_mercari_v1",
    "creema":  "genre_creema_v1",
    "minne":   "genre_minne_v1",
}

RESEARCH_GENRES = {
    # アクセサリー
    "ピアス":       "ピアス ハンドメイド",
    "イヤリング":   "イヤリング ハンドメイド",
    "ネックレス":   "ネックレス ハンドメイド",
    "ブレスレット": "ブレスレット ハンドメイド",
    "指輪":         "指輪 ハンドメイド",
    "ヘアアクセ":   "ヘアアクセサリー ハンドメイド",
    "ヘアゴム":     "ヘアゴム ハンドメイド",
    "ブローチ":     "ブローチ ハンドメイド",
    "シュシュ":     "シュシュ ハンドメイド",
    # バッグ・財布・小物
    "トートバッグ": "トートバッグ ハンドメイド",
    "バッグ":       "バッグ ハンドメイド",
    "ポーチ":       "ポーチ ハンドメイド",
    "財布":         "財布 ハンドメイド",
    "がま口":       "がま口 ハンドメイド",
    "キーケース":   "キーケース ハンドメイド",
    "キーホルダー": "キーホルダー ハンドメイド",
    "パスケース":   "パスケース ハンドメイド",
    "スマホケース": "スマホケース ハンドメイド",
    # インテリア・雑貨
    "キャンドル":     "キャンドル ハンドメイド",
    "石鹸":           "石鹸 ハンドメイド",
    "ドライフラワー": "ドライフラワー ハンドメイド",
    "リース":         "リース ハンドメイド",
    "アロマ":         "アロマ ハンドメイド",
    "タペストリー":   "タペストリー ハンドメイド",
    # ファッション
    "子供服":   "子供服 ハンドメイド",
    "帽子":     "帽子 ハンドメイド",
    "マフラー": "マフラー ハンドメイド",
    "マスク":   "マスク ハンドメイド",
    "ヘアバンド": "ヘアバンド ハンドメイド",
    # クラフト
    "刺繍":         "刺繍 ハンドメイド",
    "編み物":       "編み物 ハンドメイド",
    "レジン":       "レジン ハンドメイド",
    "レザー":       "レザー ハンドメイド",
    "ぬいぐるみ":   "ぬいぐるみ ハンドメイド",
    "羊毛フェルト": "羊毛フェルト ハンドメイド",
    "ビーズ":       "ビーズ ハンドメイド",
    # ペット
    "ペット用品": "ペット ハンドメイド",
    "ペット服":   "犬服 ハンドメイド",
}


# ─── キャッシュ操作 ───────────────────────────────────────

def _get_cached(cache_key: str) -> dict | None:
    path = cache_manager._cache_path(cache_key)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        if time.time() - payload["timestamp"] > GENRE_CACHE_TTL:
            return None
        return payload["data"]
    except Exception:
        return None


def _save_cache(cache_key: str, data: dict) -> None:
    path = cache_manager._cache_path(cache_key)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"timestamp": time.time(), "data": data}, f, ensure_ascii=False)


def last_updated(platform: str) -> float | None:
    return cache_manager.last_updated(CACHE_KEYS[platform])


def get_cached(platform: str) -> dict | None:
    return _get_cached(CACHE_KEYS[platform])


# ─── メルカリ取得（async）────────────────────────────────

async def _count(client, keyword: str, sold: bool) -> int:
    try:
        if sold:
            results = await client.search(
                keyword,
                status=[SearchRequestData.Status.STATUS_SOLD_OUT],
            )
        else:
            results = await client.search(keyword)
        raw = await _mc._fetch_pages(results, 200)
        return len(raw)
    except Exception as e:
        print(f"[genre error] {keyword} sold={sold}: {e}")
        return 0


async def _fetch_mercari_async(progress_callback=None) -> dict:
    client = _mercapi.Mercapi()
    sem = asyncio.Semaphore(3)
    genres = list(RESEARCH_GENRES.items())
    total = len(genres)
    done_count = [0]

    async def fetch_one(genre, keyword):
        async with sem:
            on_sale, sold = await asyncio.gather(
                _count(client, keyword, sold=False),
                _count(client, keyword, sold=True),
            )
            done_count[0] += 1
            if progress_callback:
                progress_callback(done_count[0] / total, genre)
            return genre, {"on_sale": on_sale, "sold": sold}

    results = await asyncio.gather(
        *[fetch_one(g, kw) for g, kw in genres],
        return_exceptions=True,
    )
    return {g: d for r in results if isinstance(r, tuple) for g, d in [r]}


# ─── 各プラットフォームの取得 ─────────────────────────────

def fetch_genre_stats(platform: str, force: bool = False, progress_callback=None) -> dict | None:
    """
    Args:
        platform: "mercari" | "creema" | "minne"
    Returns:
        {genre: {"on_sale": int, "sold": int}}
        sold は mercari のみ有効。creema/minne は常に 0。
    """
    cache_key = CACHE_KEYS[platform]

    if not force:
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

    if platform == "mercari":
        stats = asyncio.run(_fetch_mercari_async(progress_callback))

    elif platform == "creema":
        counts = creema_client.fetch_all_genre_counts(RESEARCH_GENRES, progress_callback)
        stats = {g: {"on_sale": c, "sold": 0} for g, c in counts.items()}

    elif platform == "minne":
        counts = minne_client.fetch_all_genre_counts(RESEARCH_GENRES, progress_callback)
        stats = {g: {"on_sale": c, "sold": 0} for g, c in counts.items()}

    else:
        return None

    if stats:
        _save_cache(cache_key, stats)
    return stats or None
