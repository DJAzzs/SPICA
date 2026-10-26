"""FastAPI + WebSocket 服务。

- GET /            web/dist（构建后）或内置状态页
- GET  /api/settings / POST /api/settings（向导/设置页）
- WS   /ws         二进制=麦克风 PCM(16k int16)；JSON=控制消息
- 二进制下行=TTS PCM(24k int16)，sr 由 tts 事件携带
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from server.config import ROOT, load_settings, save_settings

WEB_DIST = ROOT / "web" / "dist"


class Hub:
    """WS 连接集合 + 广播。"""

    def __init__(self):
        self.conns: set[WebSocket] = set()

    async def broadcast(self, event: dict) -> None:
        dead = []
        for ws in list(self.conns):
            try:
                await ws.send_text(json.dumps(event, ensure_ascii=False))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.conns.discard(ws)

    async def broadcast_audio(self, data: bytes, sr: int) -> None:
        dead = []
        for ws in list(self.conns):
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.conns.discard(ws)


def create_app(boot) -> FastAPI:
    """boot：async (app, hub) -> Semantics（lifespan 内组装）。"""
    app = FastAPI(title="SPICA")
    hub = Hub()
    state: dict = {"sem": None, "settings": load_settings()}

    @app.on_event("startup")
    async def _startup() -> None:
        sem = await boot(app, hub)
        state["sem"] = sem
        state["settings"] = load_settings()
        await hub.broadcast({"t": "settings", **_safe_settings()})

    def _safe_settings() -> dict:
        s = json.loads(json.dumps(state["settings"]))
        s["has_key"] = bool(s.pop("llm_api_key", None))
        s.pop("speaker_embeddings", None)
        from server.config import SPICA_IDENTITY
        s["spica_identity"] = SPICA_IDENTITY
        return s

    @app.get("/")
    async def index():
        idx = WEB_DIST / "index.html"
        if idx.exists():
            return FileResponse(idx, headers={"Cache-Control": "no-store"})
        return JSONResponse({"app": "SPICA", "status": "web 未构建",
                             "ws": "/ws"})

    # 构建产物静态资源（vite 输出 assets/）
    if (WEB_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"),
                  name="assets")

    # favicon
    @app.get("/favicon.svg")
    async def favicon():
        f = WEB_DIST / "favicon.svg"
        if f.exists():
            return FileResponse(f, media_type="image/svg+xml")
        return Response(status_code=404)


    @app.get("/api/settings")
    async def get_settings():
        return _safe_settings()

    @app.post("/api/settings")
    async def patch_settings(patch: dict):
        sem = state["sem"]
        # 试听请求：可同时携带音色字段（先保存并热更新引擎，再播）
        preview = patch.pop("tts_preview_text", None)
        voice_keys = ("tts_voice_preset", "tts_custom_description", "tts_language")
        voice_patch = {k: patch.pop(k) for k in list(patch.keys())
                       if k in voice_keys}
        merged: dict | None = None
        if voice_patch:
            merged = save_settings(voice_patch)
            state["settings"] = merged
            if sem:
                # 热更新 TTS 引擎音色（不重启）
                sem.narrator.engine.settings = merged
                sem.settings = merged
            await hub.broadcast({"t": "settings", **_safe_settings()})
        if preview and sem:
            sem.narrator.speak(str(preview), prio=1, kind="confirm")
            return {"preview": True}
        if merged is not None and not patch:
            return _safe_settings()
        merged = save_settings(patch)
        state["settings"] = merged
        if sem:
            sem.narrator.engine.settings = merged
            sem.settings = merged
        await hub.broadcast({"t": "settings", **_safe_settings()})
        return _safe_settings()

    # ---------------- 工作区文件浏览器（限当前会话工作区内，防越界）
    def _ws_root() -> Path | None:
        sem = state["sem"]
        if not sem or not sem.session.get("cwd"):
            return None
        return Path(sem.session["cwd"]).resolve()

    @app.get("/api/files/list")
    async def files_list(sub: str = ""):
        root = _ws_root()
        if not root:
            return JSONResponse({"error": "无会话工作区"}, status_code=400)
        target = (root / sub).resolve() if sub else root
        try:
            target.relative_to(root)
        except ValueError:
            return JSONResponse({"error": "路径越界"}, status_code=400)
        entries = []
        if target.exists():
            for p in sorted(target.iterdir(),
                            key=lambda x: (x.is_file(), x.name.lower())):
                if p.name in (".git", "node_modules", "__pycache__"):
                    continue
                entries.append({
                    "name": p.name, "dir": p.is_dir(),
                    "size": p.stat().st_size if p.is_file() else 0,
                })
        return {"root": str(root), "sub": sub, "entries": entries}

    @app.get("/api/files/read")
    async def files_read(path: str):
        root = _ws_root()
        if not root:
            return JSONResponse({"error": "无会话工作区"}, status_code=400)
        f = (root / path).resolve()
        try:
            f.relative_to(root)
        except ValueError:
            return JSONResponse({"error": "路径越界"}, status_code=400)
        if not f.is_file():
            return JSONResponse({"error": "不是文件"}, status_code=400)
        if f.stat().st_size > 300_000:
            return JSONResponse({"error": "文件过大（>300KB）"}, status_code=400)
        raw = f.read_bytes()[:2048]
        if b"\x00" in raw:
            return JSONResponse({"error": "二进制文件不支持预览"}, status_code=400)
        try:
            content = f.read_text("utf-8")
        except Exception:
            content = f.read_text("utf-8", errors="replace")
        return {"path": path, "content": content}

    # ---------------- 上传 / 导出 ----------------
    @app.post("/api/files/upload")
    async def files_upload(files: list[UploadFile] = File(...)):
        sem = state["sem"]
        if not sem or not sem.session.get("cwd"):
            return JSONResponse({"error": "无会话工作区"}, status_code=400)
        import re as _re
        updir = Path(sem.session["cwd"]) / "uploads"
        updir.mkdir(parents=True, exist_ok=True)
        saved = []
        for f in files:
            name = _re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", f.filename or "file")
            data = await f.read()
            (updir / name).write_bytes(data)
            saved.append(name)
        if saved:
            sem._log("system", f"上传文件：{'、'.join(saved)}")
        return {"saved": saved}

    @app.get("/api/session/export")
    async def session_export():
        import io
        import zipfile as _zip
        sem = state["sem"]
        if not sem or not sem.session.get("id"):
            return JSONResponse({"error": "无会话"}, status_code=400)
        sid = sem.session["id"]
        meta = sem.session
        events = sem.store.events(sid)
        buf = io.BytesIO()
        with _zip.ZipFile(buf, "w", _zip.ZIP_DEFLATED) as z:
            z.writestr("session.json",
                       json.dumps(meta, ensure_ascii=False, indent=2))
            z.writestr("events.jsonl", "\n".join(
                json.dumps(e, ensure_ascii=False) for e in events))
            role_label = {"user": "用户", "assistant": "SPICA",
                          "tool": "执行", "system": "系统", "rewrite": "改写"}
            md = ["# SPICA 会话导出", "",
                  f"- 标题：{meta.get('title') or '未命名'}",
                  f"- 工作区：{meta.get('cwd')}",
                  f"- 导出时间：{__import__('datetime').datetime.now().isoformat()}",
                  "", "---", ""]
            for e in events:
                md.append(f"**{role_label.get(e.get('role'), e.get('role'))}**：\n\n"
                          f"{e.get('text', '')}\n")
            z.writestr("session.md", "\n".join(md))
        buf.seek(0)
        safe = __import__("re").sub(r"[^\w\u4e00-\u9fff-]+", "_",
                                     meta.get("title") or sid)
        from fastapi.responses import Response
        return Response(
            content=buf.getvalue(), media_type="application/zip",
            headers={"Content-Disposition":
                     f"attachment; filename*=UTF-8''spica-{safe}.zip"})

    # ---------------- 音乐（代理流/封面，解决 CORS） ----------------
    @app.get("/api/files/browse")
    async def files_browse(path: str = "/"):
        """浏览任意目录（工作区选择器用）。"""
        p = Path(path).resolve()
        if not p.exists() or not p.is_dir():
            return {"path": str(p), "dirs": [], "files": []}
        dirs, files = [], []
        try:
            for c in sorted(p.iterdir()):
                if c.is_dir() and not c.name.startswith("."):
                    dirs.append(c.name)
                elif c.is_file() and not c.name.startswith("."):
                    sz = c.stat().st_size
                    files.append({"name": c.name, "size": sz})
        except PermissionError:
            pass
        return {"path": str(p), "parent": str(p.parent),
                "dirs": dirs[:80], "files": files[:50]}

    @app.delete("/api/files/uploaded")
    async def delete_uploaded(name: str):
        sem = state["sem"]
        if not sem or not sem.session.get("cwd"):
            return JSONResponse({"error": "无会话工作区"}, status_code=400)
        import re as _re
        safe = _re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name or "")
        f = (Path(sem.session["cwd"]) / "uploads" / safe).resolve()
        try:
            f.relative_to((Path(sem.session["cwd"]) / "uploads").resolve())
        except ValueError:
            return JSONResponse({"error": "路径越界"}, status_code=400)
        f.unlink(missing_ok=True)
        return {"deleted": safe}

    @app.post("/api/files/mkdir")
    async def files_mkdir(data: dict):
        """新建文件夹。"""
        import os as _os
        path = data.get("path", "")
        if not path:
            return JSONResponse({"error": "路径不能为空"}, status_code=400)
        try:
            _os.makedirs(path, exist_ok=True)
            return {"ok": True, "path": path}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/files/rename")
    async def files_rename(data: dict):
        """重命名文件/文件夹。"""
        import os as _os
        old = data.get("old", "")
        new = data.get("new", "")
        if not old or not new:
            return JSONResponse({"error": "路径不能为空"}, status_code=400)
        try:
            _os.rename(old, new)
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/files/delete")
    async def files_delete(data: dict):
        """删除文件或空文件夹。"""
        path = data.get("path", "")
        if not path:
            return JSONResponse({"error": "路径不能为空"}, status_code=400)
        import os as _os, shutil as _shutil
        try:
            if _os.path.isdir(path):
                _shutil.rmtree(path)
            else:
                _os.unlink(path)
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    # ---------------- 音乐历史 ----------------
    @app.get("/api/music/history")
    async def music_history():
        from server.media.history import list_history
        return {"list": list_history()}

    @app.delete("/api/music/history/{index}")
    async def music_history_delete(index: int):
        from server.media.history import delete_entry
        ok = delete_entry(index)
        return {"ok": ok}

    @app.delete("/api/music/history")
    async def music_history_clear():
        from server.media.history import clear_all
        count = clear_all()
        return {"cleared": count}

    @app.get("/api/music/stream")
    async def music_stream(id: str):
        from server.media.musicfree import MusicFree
        try:
            gen, ctype = await MusicFree.stream(id)
            from fastapi.responses import StreamingResponse
            return StreamingResponse(gen, media_type=ctype,
                headers={"Cache-Control": "no-store"})
        except Exception as e:
            return JSONResponse({"error": str(e)[:120]}, status_code=502)

    @app.get("/api/music/cover")
    async def music_cover(id: str):
        from server.media.musicfree import MusicFree
        try:
            data, ctype = await MusicFree.cover(id)
            return Response(content=data, media_type=ctype)
        except Exception:
            return Response(status_code=502)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        hub.conns.add(ws)
        sem = state["sem"]
        try:
            await ws.send_text(json.dumps(
                {"t": "settings", **_safe_settings()}, ensure_ascii=False))
            if sem:
                # 连接即恢复：当前会话与历史
                await ws.send_text(json.dumps(
                    {"t": "history", "msgs": sem.transcript[-200:]},
                    ensure_ascii=False))
                await sem.broadcast_sessions()
                if sem.session:
                    await ws.send_text(json.dumps(
                        {"t": "session", "meta": sem.session},
                        ensure_ascii=False))
                # 底边栏：连接即发送当前统计（不等任务）
                try:
                    await sem._send_initial_stats()
                except Exception:
                    pass
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.receive":
                    if "bytes" in msg and msg["bytes"]:
                        if sem:
                            sem.pipeline.feed_pcm(msg["bytes"])
                    elif "text" in msg and msg["text"]:
                        await _handle(ws, sem, json.loads(msg["text"]))
        except WebSocketDisconnect:
            pass
        finally:
            hub.conns.discard(ws)

    async def _handle(ws: WebSocket, sem, data: dict) -> None:
        t = data.get("t", "")
        try:
            if t == "ping":
                await ws.send_text(json.dumps({"t": "pong"}))
            elif t == "mic":
                pass
            elif t == "settings_patch":
                patch = data.get("patch", {})
                # 自动生成唤醒/结束词变体
                from server.voice.wake import auto_variants
                for wf in ("wake_words", "farewell_words"):
                    if wf in patch and isinstance(patch[wf], list):
                        for w in patch[wf]:
                            if isinstance(w, dict) and not w.get("variants"):
                                w["variants"] = auto_variants(w.get("phrase", ""))
                merged = save_settings(patch)
                state["settings"] = merged
                sem.settings = merged
                sem.pipeline.settings = merged
                sem.pipeline.wake_words = merged.get("wake_words", [])
                sem.pipeline.farewell_words = merged.get("farewell_words", [])
                sem.narrator.engine.settings = merged
                await hub.broadcast({"t": "settings", **_safe_settings()})
                await hub.broadcast({"t": "settings", **_safe_settings()})
            elif t == "wake_test":
                from server.voice.wake import Matcher
                m = Matcher()
                text = data.get("text", "")
                hit = m.match_prefix(text, sem.pipeline.wake_words, "wake")
                fw = m.match_anywhere(text, sem.pipeline.farewell_words, "farewell")
                await ws.send_text(json.dumps({
                    "t": "diag", "wake_test": bool(hit),
                    "matched": hit.phrase if hit else None,
                    "farewell": bool(fw)}, ensure_ascii=False))
            elif t == "text_input":
                await sem.on_text_input(str(data.get("text", "")))
            elif t == "manual_listen":
                await sem.manual_listen(float(data.get("seconds", 20)))
            elif t == "cancel_listen":
                await sem.cancel_listen()
            elif t == "command":
                await sem._command(str(data.get("name", "")), "手动")
            elif t == "permission_grant":
                await sem.grant_permission(str(data.get("mode", "once")))
            elif t == "music_ctrl":
                action = str(data.get("action", ""))
                if action == "play":
                    await sem.music_play(str(data.get("q", "")))
                elif action == "stop":
                    await sem.music_stop()
                else:
                    await hub.broadcast({"t": "music_ctrl", "action": action})
            elif t == "slash":
                await sem.slash(str(data.get("cmd", "")),
                                str(data.get("arg", "")))
            elif t == "session_new":
                await sem.session_new(data.get("cwd", ""), data.get("perm", ""))
            elif t == "session_open":
                await sem.session_open(str(data.get("id", "")))
            elif t == "session_delete":
                await sem.session_delete(str(data.get("id", "")))
            elif t == "session_update":
                await sem.session_update(str(data.get("id", "")),
                                         dict(data.get("patch", {})))
            elif t == "enroll_start":
                await sem.enroll_start(int(data.get("n", 3)))
            elif t == "enroll_abort":
                await sem.enroll_abort()
            elif t == "shutdown_now":
                asyncio.create_task(sem.shutdown_sequence())
            elif t == "review_get":
                await ws.send_text(json.dumps({
                    "t": "diag", "review": sem.transcript[-40:]},
                    ensure_ascii=False))
        except Exception as e:
            import traceback
            traceback.print_exc()
            await hub.broadcast({"t": "error",
                                 "message": f"{type(e).__name__}: {e}"})
            await hub.broadcast({"t": "msg", "role": "system",
                                 "text": f"出错了：{e}"})

    return app
