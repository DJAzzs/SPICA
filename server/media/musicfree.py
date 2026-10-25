"""MusicFree 集成（OpenSubsonic 兼容 API 客户端 + 音频流代理）。

适配 MusicFree（Go 版个人音乐服务器，Docker: ansgoo/music-free:latest）：
- 认证：X-API-Key 优先；否则 u/t/s（用户名+MD5(密码+盐) 自动计算）
- 搜索：GET /rest/search3?query=&f=json（远程搜索依赖服务端已装音源插件）
- 串流：GET /rest/stream?id=（服务端代理转发，解决浏览器 CORS/Referer）
- 封面：GET /rest/getCoverArt?id=
"""
from __future__ import annotations

import hashlib
import json
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
    async def _remote_search(keyword: str, count: int = 12) -> list[dict]:
        """远程插件搜索（NDJSON 流聚合），返回前端同构 song 对象。"""
        h, p = MusicFree._auth()
        songs: list[dict] = []
        async with httpx.AsyncClient(timeout=20) as c:
            async with c.stream("POST",
                    f"{MusicFree._base()}/rest/api/v1/remote-search",
                    params={**p, "f": "json"},
                    json={"keyword": keyword, "pluginNames": []},
                    headers=h) as r:
                if r.status_code != 200:
                    return []
                buf = ""
                async for chunk in r.aiter_text():
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                        except Exception:
                            continue
                        for s in d.get("songs") or []:
                            if len(songs) < count:
                                songs.append(s)
        return songs

    @staticmethod
    async def search(keyword: str, count: int = 12) -> list[dict]:
        """搜索：远程插件优先，空则回退本地库。"""
        try:
            remote = await MusicFree._remote_search(keyword, count)
        except Exception:
            remote = []
        if remote:
            return remote
        # 本地库
        h, p = MusicFree._auth()
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{MusicFree._base()}/rest/search3", params={
                **p, "query": keyword, "songCount": count,
                "albumCount": 0, "artistCount": 0, "f": "json"}, headers=h)
            body = r.json().get("subsonic-response", {})
            songs = (body.get("searchResult3") or {}).get("song") or []
            return [{"id": s.get("id", ""), "title": s.get("title", "?"),
                     "artist": s.get("artist", "?"),
                     "duration": int(s.get("duration", 0) or 0),
                     "cover": s.get("coverArt", ""), "local": True}
                    for s in (songs if isinstance(songs, list) else [songs])]

    @staticmethod
    async def pick(keyword: str) -> dict | None:
        """挑一首并确保可播：远程结果先下载入库，再定位本地流 id。"""
        import random as _r
        songs = await MusicFree.search(keyword)
        if not songs:
            return None
        song = _r.choice(songs)
        if song.get("local"):
            return song
        # 下载入库（record 需整个 song 对象）
        h, p = MusicFree._auth()
        try:
            async with httpx.AsyncClient(timeout=300) as c:
                r = await c.post(
                    f"{MusicFree._base()}/rest/api/v1/remote-download",
                    params={**p, "f": "json"},
                    json={"pluginName": song.get("plugin")
                          or "mf-plugin-gomusicdl",
                          "record": song},
                    headers=h)
                body = r.json().get("subsonic-response", {})
                meta = (body.get("metadata") or {})
                cover = meta.get("coverUrl", "")
                cover_id = cover.split("id=")[-1] if "id=" in cover else ""
        except Exception:
            cover_id = song.get("raw", {}).get("cover", "")
        # 本地定位流 id
        h, p = MusicFree._auth()
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{MusicFree._base()}/rest/search3", params={
                    **p, "query": song.get("title", ""), "songCount": 5,
                    "albumCount": 0, "artistCount": 0, "f": "json"}, headers=h)
                found = ((r.json().get("subsonic-response", {})
                          .get("searchResult3") or {}).get("song") or [])
                fl = found if isinstance(found, list) else [found]
                # 先 歌名+歌手 双匹配，再退歌名单匹配
                match = next((s for s in fl if s.get("title") == song.get("title")
                              and s.get("artist") == song.get("artist")), None) \
                    or next((s for s in fl if s.get("title") == song.get("title")), None)
                if match:
                    return {"id": match.get("id", ""),
                            "title": song.get("title", "?"),
                            "artist": song.get("artist", "?"),
                            "duration": int(song.get("durationSec", 0) or 0),
                            "cover": match.get("coverArt", "") or cover_id}
        except Exception:
            pass
        return None

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
