"""MusicFree 集成（OpenSubsonic 兼容 API 客户端 + 音频流代理）。

适配 ansgoo/music-free（Go 版个人音乐服务器）等 OpenSubsonic 实现：
- 认证：X-API-Key 头（服务间长期接入）
- 搜索：GET /rest/search3?query=&f=json
- 串流：GET /rest/stream?id=（服务端代理转发，解决浏览器 CORS/Referer）
- 封面：GET /rest/getCoverArt?id=
"""
from __future__ import annotations

import random
from typing import AsyncIterator

import httpx

from server.config import load_settings


def _cfg() -> tuple[str, str]:
    s = load_settings()
    return (s.get("musicfree_url") or "http://127.0.0.1:4533").rstrip("/"), \
        s.get("musicfree_api_key") or ""


class MusicFree:
    @staticmethod
    async def ping() -> tuple[bool, str]:
        base, key = _cfg()
        try:
            async with httpx.AsyncClient(timeout=4) as c:
                r = await c.get(f"{base}/rest/ping", params={"f": "json"},
                                headers={"X-API-Key": key})
                data = r.json().get("subsonic-response", {})
                ok = data.get("status") == "ok"
                return ok, (data.get("type", "?") + " " +
                            data.get("serverVersion", "") if ok else r.text[:80])
        except Exception as e:
            return False, repr(e)[:100]

    @staticmethod
    async def search(keyword: str, count: int = 12) -> list[dict]:
        """搜索歌曲，返回 [{id,title,artist,duration,cover}]。"""
        base, key = _cfg()
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{base}/rest/search3", params={
                "query": keyword, "songCount": count,
                "albumCount": 0, "artistCount": 0, "f": "json"},
                headers={"X-API-Key": key})
            body = r.json().get("subsonic-response", {})
            songs = (body.get("searchResult3") or {}).get("song") or []
            out = []
            for s in (songs if isinstance(songs, list) else [songs]):
                out.append({
                    "id": s.get("id", ""),
                    "title": s.get("title", "?"),
                    "artist": s.get("artist", "?"),
                    "duration": int(s.get("duration", 0) or 0),
                    "cover": s.get("coverArt", ""),
                })
            return [x for x in out if x["id"]]

    @staticmethod
    async def pick(keyword: str) -> dict | None:
        """按关键词随机挑一首（Agent 自动配乐用）。"""
        songs = await MusicFree.search(keyword)
        return random.choice(songs) if songs else None

    @staticmethod
    async def stream(id: str) -> tuple[AsyncIterator[bytes], str]:
        """代理音频流：返回 (字节迭代器, content_type)。"""
        base, key = _cfg()
        client = httpx.AsyncClient(timeout=30)
        req = client.build_request("GET", f"{base}/rest/stream",
                                   params={"id": id, "format": "raw"},
                                   headers={"X-API-Key": key})
        resp = await client.send(req, stream=True)

        async def gen():
            try:
                async for chunk in resp.aiter_bytes(65536):
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return gen(), resp.headers.get("content-type", "audio/mpeg")

    @staticmethod
    async def cover(id: str) -> tuple[bytes, str]:
        base, key = _cfg()
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{base}/rest/getCoverArt",
                            params={"id": id},
                            headers={"X-API-Key": key})
            return r.content, r.headers.get("content-type", "image/jpeg")
