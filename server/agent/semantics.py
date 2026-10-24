"""总控语义机：管线回调 / WS 消息 → 状态流转 → SDK 任务 / 播报 / 关停。

状态：idle → listen →(final+rewrite+route)→ exec →(turn/end)→ idle
      exec ←→ paused（SIGTERM/重启+resume）
      任意 → confirm_shutdown →（确认）→ shutdown
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from server import lifecycle
from server.config import (ARCHIVES_DIR, ROOT, WORKSPACE_DIR, load_settings,
                           save_settings)
from server.tts.narrator import Narrator

CONFIRM_WINDOW_S = 20.0


class Semantics:
    def __init__(self, pipeline, sdk, rewriter, router, narrator, packs,
                 speaker, broadcast, settings: dict | None = None):
        self.pipeline = pipeline
        self.sdk = sdk
        self.rewriter = rewriter
        self.router = router
        self.narrator = narrator
        self.packs = packs
        self.speaker = speaker
        self.broadcast = broadcast            # async (dict) -> None
        self.settings = settings or load_settings()
        self.state = "idle"
        self.loop: asyncio.AbstractEventLoop | None = None
        # 任务上下文（存档用）
        self.transcript: list[dict] = []      # {role, text, ts}
        self.route_info: dict = {}
        self.pending_prompts: list[str] = []
        self.last_assistant_text: str = ""
        self.current_brief: str = ""
        self._confirm_timer: asyncio.Task | None = None
        self._turn_task: asyncio.Task | None = None
        # 声纹注册
        self.enroll_mode = False
        self.enroll_target = 3
        self.enroll_samples: list[np.ndarray] = []

    def bind_loop(self) -> None:
        self.loop = asyncio.get_running_loop()

    # ================================================== 线程→asyncio 桥
    def _from_thread(self, coro_factory) -> None:
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(
                lambda: asyncio.create_task(coro_factory()))

    def pipeline_callbacks(self):
        from server.voice.pipeline import PipelineCallbacks
        return PipelineCallbacks(
            on_level=lambda r: self._from_thread(lambda: self.broadcast(
                {"t": "level", "rms": round(float(r), 4)})),
            on_wake=lambda phrase, ok, score: self._from_thread(
                lambda: self._wake(phrase, ok, score)),
            on_partial=lambda t: self._from_thread(lambda: self._partial(t)),
            on_final=lambda t: self._from_thread(lambda: self._final(t)),
            on_farewell=lambda phrase: self._from_thread(
                lambda: self._farewell(phrase)),
            on_command=lambda name, text: self._from_thread(
                lambda: self._command(name, text)),
            on_segment_audio=lambda s: self._from_thread(
                lambda: self._segment_audio(s)),
        )

    # ================================================== 唤醒/收音
    async def _set_state(self, s: str) -> None:
        self.state = s
        await self.broadcast({"t": "state", "s": s})

    async def _wake(self, phrase: str, ok: bool, score: float) -> None:
        if self.state in ("exec", "paused", "confirm_shutdown"):
            return  # 执行中唤醒词无效（插话走 final 路径/命令路径）
        await self.broadcast({"t": "wake_ack", "accepted": True,
                              "speaker_ok": True, "score": round(score, 3)})
        await self._set_state("listen")
        # 应答包（缓存直读，<10ms）
        self.narrator.speak(self.packs.wake_phrase(), prio=0, kind="wake")

    async def _partial(self, text: str) -> None:
        await self.broadcast({"t": "partial", "text": text})
        if self.enroll_mode:
            return  # 注册朗读不进改写预热（省 LLM 调用）
        # 边说边改（预热）
        def on_draft(res):
            asyncio.create_task(self.broadcast(
                {"t": "rewrite", "stage": "draft", "text": res.text}))
        try:
            await self.rewriter.prewarm(text, on_draft=on_draft)
        except Exception:
            pass

    async def _final(self, text: str) -> None:
        self.transcript.append({"role": "user", "text": text,
                                "ts": time.time()})
        await self.broadcast({"t": "final", "text": text})
        if self.enroll_mode:
            return  # 注册模式只收音频
        await self._dispatch(text)

    # ================================================== 键盘输入（与语音同管线）
    async def on_text_input(self, text: str) -> None:
        """文本输入：已是指令，跳过改写，仍做难度路由。"""
        text = (text or "").strip()
        if not text:
            return
        if self.state == "confirm_shutdown":
            from server.voice.wake import Matcher, command_entries, normalize
            m = Matcher()
            cmds = command_entries(self.settings.get("commands", {}))
            norm = normalize(text)
            if norm in ("确定", "确认", "y", "yes", "ok"):
                await self.shutdown_sequence()
            else:
                if self._confirm_timer:
                    self._confirm_timer.cancel()
                await self._set_state("exec" if self.sdk.proc else "idle")
            return
        self.transcript.append({"role": "user", "text": text, "ts": time.time()})
        await self.broadcast({"t": "final", "text": text})
        await self.broadcast({"t": "msg", "role": "user", "text": text})
        await self._after_rewrite(text)

    # ================================================== 任务分发
    async def _dispatch(self, text: str) -> None:
        if self.state == "confirm_shutdown":
            from server.voice.wake import Matcher, command_entries
            m = Matcher()
            cmds = command_entries(self.settings.get("commands", {}))
            if m.match_anywhere(text, cmds["confirm"], "command:confirm"):
                await self.shutdown_sequence()
            else:
                if self._confirm_timer:
                    self._confirm_timer.cancel()
                await self._set_state("exec" if self.sdk.proc else "idle")
                self.narrator.step("好，继续。")
            return

        result = await self.rewriter.finalize(text)
        if result.dropped or not result.text:
            self.narrator.confirm("这句没听清，请再说一次。")
            await self._set_state("listen")
            return
        await self.broadcast({"t": "rewrite", "stage": "final",
                              "text": result.text})
        self.transcript.append({"role": "rewrite", "text": result.text,
                                "ts": time.time()})
        await self._after_rewrite(result.text)

    async def _after_rewrite(self, prompt: str) -> None:
        """改写完成后的公共路径：路由 →（执行中入队 / 开新任务）。"""
        difficulty = await self.router.classify(prompt)
        route = self.router.route(difficulty, self.settings)
        self.route_info = route
        await self.broadcast({"t": "route", **route})
        await self.broadcast({"t": "msg", "role": "system",
                              "text": f"路由：{route.get('model')} · {difficulty}"})

        if self.state == "exec":
            # 执行中插话：入队，turn 结束后送达
            self.pending_prompts.append(prompt)
            self.narrator.step("收到，记下了，当前任务完成后就做。")
            return

        await self._start_task(prompt)

    async def _start_task(self, prompt: str) -> None:
        route = self.route_info or self.router.route("normal", self.settings)
        if not self.sdk.proc:
            await self.sdk.start(route["model"], route.get("reasoning_effort"))
            await self.broadcast({"t": "state", "s": "exec",
                                  "session": self.sdk.session_id})
        else:
            await self.broadcast({"t": "state", "s": "exec"})
        self.state = "exec"
        self.current_brief = prompt[:40]
        self.narrator.speak(f"收到，开始：{self.current_brief}", prio=1,
                            kind="confirm")
        self.transcript.append({"role": "task", "text": prompt,
                                "ts": time.time()})
        await self.sdk.prompt(prompt)

    # ================================================== SDK 通知
    async def on_sdk_notification(self, method: str, params: dict) -> None:
        if method == "session.status":
            return
        if method != "session.event":
            return
        ev = params.get("event", {})
        typ = ev.get("type", "")
        data = ev.get("data", {}) or {}
        if typ == "assistant/message":
            msg = data.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    text = block["text"].strip()
                    self.last_assistant_text = text
                    await self.broadcast({"t": "msg", "role": "assistant",
                                          "text": text})
                elif block.get("type") in ("tool_call", "tool_use"):
                    summary = self.narrator.tool_summary(
                        block.get("name", "tool"),
                        block.get("arguments") or block.get("input") or "")
                    await self.broadcast({"t": "msg", "role": "tool",
                                          "text": summary})
        elif typ in ("tool/call", "tool/use"):
            summary = self.narrator.tool_summary(
                data.get("name") or data.get("tool") or "tool",
                data.get("arguments") or data.get("input")
                or data.get("args") or data.get("command") or "")
            await self.broadcast({"t": "msg", "role": "tool",
                                  "text": summary})
        elif typ == "tool/result":
            out = (data.get("result") or data.get("output") or "")
            if isinstance(out, str) and out.strip():
                await self.broadcast({"t": "msg", "role": "tool",
                                      "text": f"结果：{out.strip()[:120]}"})
        await self.broadcast({"t": "step", "type": typ})
        self.narrator.on_agent_event(ev)
        if typ == "turn/end":
            self._turn_task = asyncio.create_task(self._turn_done())

    async def _turn_done(self) -> None:
        summary = self.last_assistant_text[:200] or "任务执行完毕。"
        self.transcript.append({"role": "assistant", "text": summary,
                                "ts": time.time()})
        await self.broadcast({"t": "task_done", "summary": summary})
        nickname = self.settings.get("user_nickname", "")
        call = f"{nickname}，" if nickname else ""
        self.narrator.final(f"{summary}……{call}任务完成，请指示。")
        await self._set_state("idle")
        if self.pending_prompts:
            nxt = self.pending_prompts.pop(0)
            await asyncio.sleep(1.0)
            await self._start_task(nxt)

    # ================================================== 语义命令
    async def _command(self, name: str, text: str) -> None:
        if name == "pause":
            if self.state == "exec":
                self.sdk.pause()
                self.narrator.confirm("已暂停，说「继续」可以接着做。")
                await self._set_state("paused")
        elif name == "resume":
            if self.state == "paused":
                route = self.route_info or {}
                await self.sdk.start(route.get("model") or "glm-5.3",
                                     route.get("reasoning_effort"))
                await self.sdk.resume(self.sdk.session_id)
                await self.sdk.prompt("继续刚才的任务。")
                self.narrator.confirm("好，继续。")
                await self._set_state("exec")
        elif name == "confirm":
            if self.state == "confirm_shutdown":
                if self._confirm_timer:
                    self._confirm_timer.cancel()
                await self.shutdown_sequence()
        elif name == "cancel":
            if self.state == "confirm_shutdown":
                if self._confirm_timer:
                    self._confirm_timer.cancel()
                await self._set_state("exec" if self.sdk.proc else "idle")

    # ================================================== 结束词
    async def _farewell(self, phrase: str) -> None:
        if self.state == "exec" and self.sdk.proc:
            self.narrator.confirm("任务还在执行，确定要结束吗？")
            await self._set_state("confirm_shutdown")

            async def back():
                await asyncio.sleep(CONFIRM_WINDOW_S)
                if self.state == "confirm_shutdown":
                    await self._set_state("exec")
                    self.narrator.step("继续执行。")
            self._confirm_timer = asyncio.create_task(back())
        else:
            await self.shutdown_sequence()

    # ================================================== 关停序列
    async def shutdown_sequence(self) -> None:
        try:
            await self._set_state("shutdown")
            # 1. 停 DSH
            try:
                await self.sdk.stop()
            except Exception:
                pass
            # 2. 存档
            path = await asyncio.to_thread(self._archive)
            await self.broadcast({"t": "archive_done", "path": str(path)})
            # 3. 告别语音
            self.narrator.speak(self.packs.farewell_phrase(), prio=0,
                                kind="farewell")
            for _ in range(120):  # 等播完（最多 30s）
                if not self.narrator.speaking and self.narrator.q.empty():
                    break
                await asyncio.sleep(0.25)
            # 4. 浏览器告别画面
            await self.broadcast({"t": "shutdown"})
            await asyncio.sleep(1.0)
        finally:
            # 5. 拆链 + 自停（幂等）
            try:
                lifecycle.killall(verbose=False)
            except Exception:
                pass
            self.self_stop()

    def self_stop(self) -> None:
        """默认 SIGTERM 自停；测试注入替身。"""
        os.kill(os.getpid(), signal.SIGTERM)

    def _archive(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        sid = self.sdk.session_id or "no-session"
        d = ARCHIVES_DIR / f"{ts}-{sid[:16]}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "events.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False)
                      for e in self.transcript), "utf-8")
        md = ["# SPICA 会话存档", "",
              f"- 时间：{datetime.now().isoformat()}",
              f"- DSH 会话：{sid}",
              f"- 路由：{json.dumps(self.route_info, ensure_ascii=False)}", "",
              "## 对话", ""]
        for e in self.transcript:
            md.append(f"- **{e['role']}**：{e['text']}")
        md += ["", "## 播报记录", ""]
        md += [f"- {h}" for h in self.narrator.history] or ["-（无）"]
        (d / "session.md").write_text("\n".join(md), "utf-8")
        # workspace git commit（可关）
        if self.settings.get("archive_git_commit", True):
            try:
                subprocess.run(["git", "init", "-q"], cwd=WORKSPACE_DIR,
                               capture_output=True)
                subprocess.run(["git", "add", "-A"], cwd=WORKSPACE_DIR,
                               capture_output=True)
                subprocess.run(
                    ["git", "-c", "user.name=SPICA", "-c",
                     "user.email=spica@local", "commit", "-qm",
                     f"SPICA 存档 {ts}", "--allow-empty"],
                    cwd=WORKSPACE_DIR, capture_output=True, timeout=30)
            except Exception:
                pass
        return d

    # ================================================== 声纹注册
    # 设计要点：注册过程**零 TTS**（引导/计数全走界面视觉），
    # 否则自己的声音会被收进样本；段音频经管线门控+回声过滤后才到达这里。
    async def enroll_start(self, n: int = 3) -> None:
        self.enroll_mode = True
        self.enroll_target = n
        self.enroll_samples = []
        self.pipeline.arm_listening(seconds=120)
        await self._set_state("listen")
        await self.broadcast({"t": "diag", "enroll": {
            "phase": "start", "got": 0, "target": n}})

    async def enroll_abort(self) -> None:
        self.enroll_mode = False
        await self.broadcast({"t": "diag", "enroll": {"phase": "abort"}})
        await self._set_state("idle")

    async def _segment_audio(self, samples: np.ndarray) -> None:
        if not self.enroll_mode:
            return
        dur = samples.size / 16000.0
        if dur < 1.2:
            # 过短（多为回声尾巴/误触发）：不计，界面提示重说
            await self.broadcast({"t": "diag", "enroll": {
                "phase": "too_short",
                "got": len(self.enroll_samples), "target": self.enroll_target}})
            self.pipeline.arm_listening(seconds=60)
            return
        self.enroll_samples.append(samples)
        got = len(self.enroll_samples)
        if got < self.enroll_target:
            await self.broadcast({"t": "diag", "enroll": {
                "phase": "progress", "got": got, "target": self.enroll_target}})
            self.pipeline.arm_listening(seconds=60)
            return
        self.enroll_mode = False
        ok = False
        if self.speaker is not None:
            ok = await asyncio.to_thread(self.speaker.enroll, self.enroll_samples)
        await self.broadcast({"t": "diag", "enroll": {
            "phase": "done", "ok": bool(ok)}})
        # 注册完成才说话（采集已结束，无自采风险）
        self.narrator.confirm(
            "声纹注册完成，现在我只回应你的声音了。" if ok
            else "注册失败，请重试。")
        await self._set_state("idle")
