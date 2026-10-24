"""SPICA 主入口：组装一切并启动。

    .venv/bin/python -m server.main   （或 make up）

组装顺序：
  FastAPI(lifespan) → Hub → 语音管线(线程) → TTS引擎(懒加载+后台预热)
  → Narrator → Rewriter/Router → SdkClient → Semantics(状态机)
后台预热：TTS 模型加载 + 唤醒/告别应答包预合成（首次启动约 30-60s CPU，
GPU 桌面数秒；之后全部走缓存）。
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

# --- Triton JIT 头文件兜底（Blackwell 上 torch cu130 部分内核走 Triton JIT，
#     venv 3.12 无 python3.12-dev 时借 3.11 头；C-API 稳定子集，已验证）。
if "CPATH" not in os.environ:
    _py311 = Path("/usr/include/python3.11/Python.h")
    _py312 = Path("/usr/include/python3.12/Python.h")
    if _py311.exists() and not _py312.exists():
        os.environ["CPATH"] = "/usr/include/python3.11"

import uvicorn

from server.agent.llm import LLMClient
from server.agent.rewriter import Rewriter
from server.agent.router import Router
from server.agent.sdk_client import SdkClient
from server.agent.semantics import Semantics
from server.config import load_settings
from server.tts.engine import TTSEngine
from server.tts.narrator import Narrator
from server.tts.packs import VoicePacks
from server.voice.pipeline import VoicePipeline
from server.voice.speaker import SpeakerGate
from server.ws.server import create_app


async def boot(app, hub) -> Semantics:
    settings = load_settings()
    print("[spica] 组件组装…", flush=True)

    # 语音管线（线程消费麦克风流）
    sem_holder: dict = {}

    pipeline = VoicePipeline(
        settings=settings,
        callbacks=None,  # semantics 绑定后回填
        speaker=SpeakerGate(),
        start=False,
    )
    pipeline.start()

    # TTS
    engine = TTSEngine(settings)
    packs = VoicePacks(engine)

    async def broadcast(event: dict) -> None:
        await hub.broadcast(event)

    async def broadcast_audio(data: bytes, sr: int) -> None:
        await hub.broadcast_audio(data, sr)

    llm = LLMClient(settings)
    narrator = Narrator(engine, broadcast, broadcast_audio,
                        on_speaking=pipeline.set_tts_gate, llm=llm)
    narrator.start()
    pipeline.echo_provider = narrator.echo_match   # 自身回声判定
    rewriter = Rewriter(llm)
    router = Router(llm)

    async def on_note(method: str, params: dict) -> None:
        sem = sem_holder.get("sem")
        if sem:
            await sem.on_sdk_notification(method, params)

    sdk = SdkClient(on_notification=on_note, settings=settings)

    sem = Semantics(pipeline, sdk, rewriter, router, narrator, packs,
                    pipeline.speaker, broadcast, settings)
    sem.bind_loop()
    sem_holder["sem"] = sem
    pipeline.cb = sem.pipeline_callbacks()   # 回填真实回调
    await broadcast({"t": "state", "s": "idle"})

    # 后台预热：TTS 模型 + 应答包（不阻塞启动）
    async def warmup() -> None:
        try:
            print("[spica] TTS 预热（首启较慢，之后走缓存）…", flush=True)
            n = await asyncio.to_thread(packs.ensure)
            print(f"[spica] 应答包就绪（{n} 条）", flush=True)
        except Exception as e:
            print(f"[spica] TTS 预热失败（首次合成时重试）：{e}", flush=True)

    asyncio.create_task(warmup())
    return sem


def main() -> None:
    settings = load_settings()
    # Ctrl+C / SIGTERM：清理全部子进程再退出（不留 dsh 残尸）
    import signal
    import subprocess

    def _cleanup(sig, frame):
        try:
            from server import lifecycle
            lifecycle.killall(verbose=False)
        finally:
            raise SystemExit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    # 版本戳：日志与界面可对齐（防"新前端旧后端"错配）
    try:
        git_hash = subprocess.run(
            ["git", "log", "-1", "--format=%h %ci"],
            capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except Exception:
        git_hash = "?"
    print(f"[spica] 版本：{git_hash}", flush=True)

    app = create_app(boot)
    uvicorn.run(app, host=settings.get("host", "127.0.0.1"),
                port=int(settings.get("port", 8666)), log_level="info")


if __name__ == "__main__":
    main()
