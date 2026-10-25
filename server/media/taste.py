"""音乐偏好学习（json 持久化，喜好/探索加权）。

run/music-taste.json:
  { keywords: {kw: count}, artists: {name: count}, total: N,
    recent: [{kw, title, artist, ts}] (最近 40 首) }

策略：无具体歌名的请求（"来点音乐"）→
  70% 从历史关键词按 count^0.7 加权采样（喜好主导，长尾仍有机会）
  30% 随机新风格（探索，避免茧房）
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

from server.config import ROOT

TASTE_FILE = ROOT / "run" / "music-taste.json"
EXPLORE_POOL = ["轻音乐", "钢琴曲", "流行热门", "city pop", "爵士", "电子专注",
                "粤语经典", "民谣", "R&B", "摇滚经典", "日语流行", "古典",
                "英文抒情", "嘻哈", "原声带", "沙发音乐"]
MAX_RECENT = 40


class MusicTaste:
    def __init__(self, path: Path | None = None):
        self.path = path or TASTE_FILE
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text("utf-8"))
            except Exception:
                pass
        return {"keywords": {}, "artists": {}, "total": 0, "recent": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                             "utf-8")

    # ------------------------------------------------------------ 记录
    def record(self, keyword: str, title: str, artist: str) -> None:
        kw = (keyword or "").strip()
        if kw:
            self.data["keywords"][kw] = self.data["keywords"].get(kw, 0) + 1
        ar = (artist or "").strip()
        if ar:
            self.data["artists"][ar] = self.data["artists"].get(ar, 0) + 1
        self.data["total"] = self.data.get("total", 0) + 1
        self.data["recent"].append({"kw": kw, "title": title, "artist": artist,
                                    "ts": time.time()})
        self.data["recent"] = self.data["recent"][-MAX_RECENT:]
        self._save()

    # ------------------------------------------------------------ 推荐
    def suggest(self, explore_ratio: float = 0.3) -> tuple[str, bool]:
        """返回 (关键词, 是否探索)。喜好按 count^0.7 加权（长尾保机会）。"""
        kws = self.data.get("keywords") or {}
        if not kws or random.random() < explore_ratio:
            return random.choice(EXPLORE_POOL), True
        items = list(kws.items())
        weights = [c ** 0.7 for _, c in items]
        kw = random.choices([k for k, _ in items], weights=weights, k=1)[0]
        return kw, False

    def summary(self) -> str:
        top_kw = sorted((self.data.get("keywords") or {}).items(),
                        key=lambda x: -x[1])[:5]
        top_ar = sorted((self.data.get("artists") or {}).items(),
                        key=lambda x: -x[1])[:5]
        return (f"共 {self.data.get('total', 0)} 首；常听关键词："
                + "、".join(f"{k}({c})" for k, c in top_kw)
                + ("；常听歌手：" + "、".join(f"{a}({c})" for a, c in top_ar)
                   if top_ar else ""))
