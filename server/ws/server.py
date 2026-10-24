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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
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
        s.pop("llm_api_key", None)
        s.pop("speaker_embeddings", None)
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

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        hub.conns.add(ws)
        sem = state["sem"]
        try:
            await ws.send_text(json.dumps(
                {"t": "settings", **_safe_settings()}, ensure_ascii=False))
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
                merged = save_settings(data.get("patch", {}))
                state["settings"] = merged
                sem.settings = merged
                sem.pipeline.settings = merged
                sem.pipeline.wake_words = merged.get("wake_words", [])
                sem.pipeline.farewell_words = merged.get("farewell_words", [])
                sem.narrator.engine.settings = merged
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
