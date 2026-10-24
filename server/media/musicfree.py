"""MusicFree 集成（OpenSubsonic 兼容 API 客户端 + 音频流代理）。

适配 MusicFree（Go 版个人音乐服务器，Docker: ansgoo/music-free:latest）：
- 认证：X-API-Key 优先；否则 u/t/s（用户名+MD5(密码+盐) 自动计算）
- 搜索：GET /rest/search3?query=&f=json（远程搜索依赖服务端已装音源插件）
- 串流：GET /rest/stream?id=（服务端代理转发，解决浏览器 CORS/Referer）
- 封面：GET /rest/getCoverArt?id=
"""
from __future__ import annotations

import hashlib
import random
import string
from typing import AsyncIterator

import httpx

from server.config import load_settings


class MusicFree:
    @staticmethod
    def _auth() -> tuple[dict, dict]:
        """返回 (headers, base_params)。"""
        s = load_settings()
        base = (s.get("musicfree_url") or "http://127.0.0.1:14533").rstrip("/")
        headers: dict = {}
        params: dict = {}
        key = s.get("musicfree_api_key") or ""
        if key:
            headers["X-API-Key"] = key
        elif s.get("musicfree_user"):
            salt = "".join(random.choices(string.ascii_letters + string.digits, k=8))
            token = hashlib.md5(
                (s.get("musicfree_pass", "") + salt).encode()).hexdigest()
            params.update({"u": s.get("musicfree_user"), "t": token, "s": salt})
        return headers, params

    @staticmethod
    def _base() -> str:
        s = load_settings()
        return (s.get("musicfree_url") or "http://127.0.0.1:14533").rstrip("/")

    @staticmethod
    async def ping() -> tuple[bool, str]:
        h, p = MusicFree._auth()
        try:
            async with httpx.AsyncClient(timeout=4) as c:
                r = await c.get(f"{MusicFree._base()}/rest/ping",
                                params={**p, "f": "json"}, headers=h)
                data = r.json().get("subsonic-response", {})
                ok = data.get("status") == "ok"
                return ok, (f"{data.get('type', '?')} {data.get('serverVersion', '')}"
                            if ok else r.text[:80])
        except Exception as e:
            return False, repr(e)[:100]

    @staticmethod
    async def search(keyword: str, count: int = 12) -> list[dict]:
        """搜索歌曲（本地库 + 远程插件），返回 [{id,title,artist,duration,cover}]。"""
        h, p = MusicFree._auth()
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(f"{MusicFree._base()}/rest/search3", params={
                **p, "query": keyword, "songCount": count,
                "albumCount": 0, "artistCount": 0, "f": "json"}, headers=h)
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
        h, p = MusicFree._auth()
        client = httpx.AsyncClient(timeout=30)
        req = client.build_request("GET", f"{MusicFree._base()}/rest/stream",
                                   params={**p, "id": id, "format": "raw"},
                                   headers=h)
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
        h, p = MusicFree._auth()
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{MusicFree._base()}/rest/getCoverArt",
                            params={**p, "id": id}, headers=h)
            return r.content, r.headers.get("content-type", "image/jpeg")
