"""音乐播放历史 — 查看/删除/清空，同步偏好 JSON。"""

import json
import time
from pathlib import Path

HISTORY_FILE = Path("run") / "music-history.json"
MAX_HISTORY = 100


def _load() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text("utf-8"))
        except Exception:
            pass
    return []


def _save(items: list) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")


def record(title: str, artist: str, keyword: str = "") -> None:
    """播放时记录。"""
    items = _load()
    items.append({"title": title, "artist": artist,
                  "keyword": keyword, "ts": time.time()})
    items = items[-MAX_HISTORY:]
    _save(items)


def list_history() -> list:
    return _load()


def delete_entry(index: int) -> bool:
    """删除单条（同步从偏好减计数）。"""
    items = _load()
    if 0 <= index < len(items):
        entry = items.pop(index)
        _save(items)
        # 同步偏好
        _decrement_taste(entry.get("keyword", ""),
                         entry.get("title", ""))
        return True
    return False


def clear_all() -> int:
    """清空全部（重置偏好）。"""
    items = _load()
    count = len(items)
    _save([])
    # 重置偏好
    taste_file = Path("run") / "music-taste.json"
    if taste_file.exists():
        taste_file.write_text(
            json.dumps({"keywords": {}, "artists": {}, "total": 0, "recent": []},
                       ensure_ascii=False, indent=2), "utf-8")
    return count


def _decrement_taste(keyword: str, title: str) -> None:
    """从偏好中减去对应计数。"""
    taste_file = Path("run") / "music-taste.json"
    if not taste_file.exists():
        return
    try:
        taste = json.loads(taste_file.read_text("utf-8"))
        kws = taste.get("keywords", {})
        if keyword in kws:
            kws[keyword] -= 1
            if kws[keyword] <= 0:
                del kws[keyword]
        arts = taste.get("artists", {})
        # 减歌手计数（如果有）
        taste_file.write_text(json.dumps(taste, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass
