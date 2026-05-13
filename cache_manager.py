import time
import json
from pathlib import Path

CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_TTL = 60 * 60 * 2  # 2時間


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    safe = key.replace(" ", "_").replace("/", "_")
    return CACHE_DIR / f"{safe}.json"


def get(key: str) -> dict | None:
    """キャッシュからデータを取得。期限切れ or 未存在なら None"""
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        if time.time() - payload["timestamp"] > CACHE_TTL:
            return None
        return payload["data"]
    except Exception:
        return None


def set(key: str, data: dict) -> None:
    path = _cache_path(key)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"timestamp": time.time(), "data": data}, f, ensure_ascii=False)


def clear(key: str | None = None) -> None:
    if key:
        _cache_path(key).unlink(missing_ok=True)
    else:
        for p in CACHE_DIR.glob("*.json"):
            p.unlink(missing_ok=True)


def last_updated(key: str) -> float | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("timestamp")
    except Exception:
        return None
