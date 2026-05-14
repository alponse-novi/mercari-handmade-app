import asyncio
import json
import time
from pathlib import Path

import cache_manager
import mercari_client as _mc  # noqa: F401 — apply httpx patches before mercapi import

import mercapi as _mercapi
from mercapi.requests import SearchRequestData

GENRE_CACHE_KEY = "genre_stats_v1"
GENRE_CACHE_TTL = 60 * 60 * 12  # 12時間
GENRE_LIMIT = 50

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
    "キャンドル":       "キャンドル ハンドメイド",
    "石鹸":             "石鹸 ハンドメイド",
    "ドライフラワー":   "ドライフラワー ハンドメイド",
    "リース":           "リース ハンドメイド",
    "アロマ":           "アロマ ハンドメイド",
    "タペストリー":     "タペストリー ハンドメイド",
    # ファッション
    "子供服":   "子供服 ハンドメイド",
    "帽子":     "帽子 ハンドメイド",
    "マフラー": "マフラー ハンドメイド",
    "マスク":   "マスク ハンドメイド",
    "ヘアバンド": "ヘアバンド ハンドメイド",
    # クラフト
    "刺繍":       "刺繍 ハンドメイド",
    "編み物":     "編み物 ハンドメイド",
    "レジン":     "レジン ハンドメイド",
    "レザー":     "レザー ハンドメイド",
    "ぬいぐるみ": "ぬいぐるみ ハンドメイド",
    "羊毛フェルト": "羊毛フェルト ハンドメイド",
    "ビーズ":     "ビーズ ハンドメイド",
    # ペット
    "ペット用品": "ペット ハンドメイド",
    "ペット服":   "犬服 ハンドメイド",
}


def get_cached() -> dict | None:
    path = cache_manager._cache_path(GENRE_CACHE_KEY)
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


def last_updated() -> float | None:
    return cache_manager.last_updated(GENRE_CACHE_KEY)


async def _count(client, keyword: str, sold: bool) -> int:
    try:
        if sold:
            results = await client.search(
                keyword,
                status=[SearchRequestData.Status.STATUS_SOLD_OUT],
            )
        else:
            results = await client.search(keyword)
        return len(list(results.items or []))
    except Exception as e:
        print(f"[genre error] {keyword} sold={sold}: {e}")
        return 0


async def _fetch_all_async(progress_callback=None) -> dict:
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


def fetch_genre_stats(force: bool = False, progress_callback=None) -> dict | None:
    if not force:
        cached = get_cached()
        if cached is not None:
            return cached

    stats = asyncio.run(_fetch_all_async(progress_callback))
    if stats:
        path = cache_manager._cache_path(GENRE_CACHE_KEY)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "data": stats}, f, ensure_ascii=False)
    return stats or None
