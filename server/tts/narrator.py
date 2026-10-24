"""TTS 播报器：语义事件 → 一句人话 → 合成 → WS 音频流。

- 优先级队列：final(0) > confirm(1) > step(2)；step 积压 >2 时丢弃旧的。
- 播报期间通知 pipeline 关闭唤醒匹配门（防自唤醒）。
- recent：最近播报文本（归一化），供管线做自身回声判定。
- 音频协议：先发 JSON {t:"tts", speaking:true, text, sr} 再发二进制
  24kHz mono int16 PCM 分块，最后 {t:"tts", speaking:false}。
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from server.tts.engine import TTSEngine
from server.voice.wake import normalize

try:
    from rapidfuzz import fuzz
    _HAVE_FUZZ = True
except Exception:  # pragma: no cover
    _HAVE_FUZZ = False

PRIO_FINAL, PRIO_CONFIRM, PRIO_STEP = 0, 1, 2


@dataclass
class SpeakJob:
    text: str
    prio: int
    kind: str          # wake | step | final | confirm | farewell


CONDENSE_SYSTEM = (
    "你是语音播报压缩器。把给定的 Agent 工作消息压缩成一句不超过 {limit} 字的"
    "中文口语短句：保留关键动作和结论，去掉路径、代码、重复细节。"
    "只输出短句本身。"
)


class Narrator:
    def __init__(self, engine: TTSEngine,
                 broadcast,              # async (dict) -> None  JSON 事件
                 broadcast_audio,        # async (bytes, sr) -> None
                 on_speaking: Optional[Callable[[bool], None]] = None,
                 llm=None):              # LLMClient（长文本缩句用）
        self.engine = engine
        self.broadcast = broadcast
        self.broadcast_audio = broadcast_audio
        self.on_speaking = on_speaking or (lambda b: None)
        self.llm = llm
        self.q: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._worker: asyncio.Task | None = None
        self._last_step_at: dict[str, float] = {}
        self.history: list[str] = []        # 播报记录（存档用）
        self.speaking = False
        self.recent: deque[str] = deque(maxlen=6)   # 最近播报（回声判定）

    def echo_match(self, text: str) -> bool:
        """判定一段转写是否是自身播报的回声（AEC 漏网）。"""
        n = normalize(text)
        if not n:
            return True
        for r in self.recent:
            if not r:
                continue
            if len(n) >= 4 and len(r) >= 4 and (n in r or r in n):
                return True
            if len(n) >= 6 and _HAVE_FUZZ and fuzz.partial_ratio(n, r) >= 88:
                return True
        return False

    def start(self) -> None:
        if not self._worker:
            self._worker = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            prio, seq, job = await self.q.get()
            try:
                await self._speak(job)
            except Exception:
                pass
            finally:
                self.q.task_done()

    # ------------------------------------------------------------ 入队
    def speak(self, text: str, prio: int = PRIO_STEP, kind: str = "step",
              dedup: bool = False) -> None:
        text = (text or "").strip()
        if not text:
            return
        if dedup:
            now = time.time()
            if now - self._last_step_at.get(text, 0) < 30:
                return
            self._last_step_at[text] = now
        # step 积压丢弃：队列中 prio>=2 的旧 job 淘汰到最多 1 个
        if prio >= PRIO_STEP:
            steps = [i for i in self.q._queue if i[2].prio >= PRIO_STEP]  # noqa
            if len(steps) >= 2:
                try:
                    self.q._queue.remove(steps[0])  # noqa
                except Exception:
                    pass
        self.q.put_nowait((prio, time.monotonic_ns(), SpeakJob(text, prio, kind)))

    def step(self, text: str) -> None:
        self.speak(text, PRIO_STEP, "step", dedup=True)

    def final(self, text: str) -> None:
        self.speak(text, PRIO_FINAL, "final")

    def confirm(self, text: str) -> None:
        self.speak(text, PRIO_CONFIRM, "confirm")

    # ------------------------------------------------------------ 合成播报
    async def _condense(self, text: str, kind: str) -> str:
        """长文本压缩成短口播（失败/超时回退原文）。"""
        limit = 40 if kind == "final" else 24
        try:
            out = await self.llm.chat(  # type: ignore[union-attr]
                [{"role": "system",
                  "content": CONDENSE_SYSTEM.format(limit=limit)},
                 {"role": "user", "content": text}],
                max_tokens=96,
                temperature=0.2,
                thinking="disabled",
                timeout=8.0,
            )
            out = (out or "").strip().strip('"').strip('「」')
            if out and 1 < len(out) < len(text):
                return out
        except Exception:
            pass
        return text

    async def _speak(self, job: SpeakJob) -> None:
        spoken = job.text
        # 超过 36 字的步骤/总结：先压缩再播（口语节奏）
        if self.llm and len(spoken) > 36 and job.kind in ("step", "final"):
            spoken = await self._condense(spoken, job.kind)
        pcm, sr = self.engine.synth(spoken)
        if pcm.size == 0:
            return
        self.speaking = True
        self.on_speaking(True)
        self.history.append(f"[{job.kind}] {job.text}")
        self.recent.append(normalize(job.text))
        try:
            await self.broadcast({"t": "tts", "speaking": True,
                                  "text": job.text, "sr": sr, "kind": job.kind})
            # ~0.4s 分块下发
            chunk = int(sr * 0.4)
            for i in range(0, pcm.size, chunk):
                await self.broadcast_audio(pcm[i:i + chunk].tobytes(), sr)
            await self.broadcast({"t": "tts", "speaking": False})
        finally:
            self.speaking = False
            self.on_speaking(False)

    # ------------------------------------------------------------ 事件映射
    @staticmethod
    def tool_summary(name: str, args: dict | str) -> str:
        """工具调用 → 一句人话（模板优先，超长截断）。"""
        args_s = args if isinstance(args, str) else str(args)
        args_s = " ".join(args_s.split())[:60]
        table = {
            "bash": "执行命令",
            "read": "查看文件",
            "write": "写入文件",
            "edit": "修改文件",
            "glob": "查找文件",
            "grep": "搜索内容",
            "web_search": "联网搜索",
            "web_fetch": "读取网页",
        }
        verb = table.get(name, f"调用 {name}")
        detail = f"：{args_s}" if args_s else ""
        return f"{verb}{detail}"

    def on_agent_event(self, ev: dict) -> None:
        """SDK session.event → 播报。宽容解析。"""
        typ = ev.get("type", "")
        data = ev.get("data", {}) or {}
        if typ == "assistant/message":
            msg = data.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    self.step(block["text"].strip()[:80])
                elif block.get("type") in ("tool_call", "tool_use"):
                    self.step(self.tool_summary(
                        block.get("name", "tool"),
                        block.get("arguments") or block.get("input") or ""))
        elif typ == "turn/end":
            reason = ((data.get("reason") or {}).get("kind", ""))
            if reason and reason != "completed":
                self.step(f"本轮结束（{reason}）")
