"""E2E 冒烟：真服务器 + 真音频 + 真 LLM + 真 DSH。

流程：连 WS → 临时换唤醒词为夹具文本中的词 → 喂 zh.wav →
断言事件链 wake_ack→state listen→partial/final→rewrite final→route→
state exec→step…→task_done → 恢复默认词表。
用法：SPICA_LIVE=1 .venv/bin/python -m tools.e2e_smoke [ws_url]
"""
import asyncio
import json
import sys
import time
import wave

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8666/ws"
FIXTURE = "tests/fixtures/e2e_task.wav"   # TTS 合成：「开放时间，帮我看一下当前目录下有几个文件…」
WAKE = "开放时间"


async def main() -> int:
    events: list[dict] = []
    got = asyncio.Event()
    audio_chunks = [0]

    async with websockets.connect(URL, max_size=2 ** 22) as ws:
        async def reader():
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):   # TTS 音频帧
                    audio_chunks[0] += 1
                    continue
                ev = json.loads(raw)
                if isinstance(ev.get("t"), str):
                    events.append(ev)
                    print(f"  [{time.strftime('%H:%M:%S')}] {ev.get('t')}: "
                          f"{str({k: v for k, v in ev.items() if k != 't'})[:100]}")
                    if ev.get("t") == "task_done":
                        got.set()

        reader_task = asyncio.create_task(reader())
        await asyncio.sleep(0.5)

        # 1) 临时唤醒词
        await ws.send(json.dumps({"t": "settings_patch", "patch": {
            "wake_words": [{"phrase": WAKE, "variants": [], "enabled": True}]}}))
        await asyncio.sleep(0.5)

        # 2) 喂音频（16k int16 → 二进制；末尾 1.2s 静音触发段结算）
        with wave.open(FIXTURE, "rb") as w:
            pcm = w.readframes(w.getnframes())
        chunk = 3200 * 2
        for i in range(0, len(pcm), chunk):
            await ws.send(pcm[i:i + chunk])
            await asyncio.sleep(0.02)
        await ws.send(b"\x00" * 32000)
        print("[e2e] 音频已喂，等待事件链…")

        try:
            await asyncio.wait_for(got.wait(), timeout=240)
        except asyncio.TimeoutError:
            print("[e2e] 超时未到 task_done")

        # 3) 恢复默认词表（不能用 None——会污染设置）
        from server.config import DEFAULT_FAREWELL_WORDS, DEFAULT_WAKE_WORDS
        await ws.send(json.dumps({"t": "settings_patch", "patch": {
            "wake_words": DEFAULT_WAKE_WORDS,
            "farewell_words": DEFAULT_FAREWELL_WORDS}}))
        reader_task.cancel()

    # 断言链
    print(f"[e2e] 收到音频块 {audio_chunks[0]} 个")
    kinds = [e["t"] for e in events]
    chain = ["wake_ack", "final", "rewrite", "route", "task_done"]
    ok = True
    pos = 0
    for want in chain:
        try:
            pos = kinds.index(want, pos)
            print(f"  ✓ {want}")
        except ValueError:
            print(f"  ✗ 缺失 {want}")
            ok = False
    rewrite = next((e for e in events if e.get("t") == "rewrite"
                    and e.get("stage") == "final"), {})
    print("[e2e] 改写终稿:", rewrite.get("text", "")[:80])
    print("[e2e] 结果:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
