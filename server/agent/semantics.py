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
from server.sessions import PERMS, SessionStore
from server.tts.narrator import Narrator

CONFIRM_WINDOW_S = 20.0


class Semantics:
    def __init__(self, pipeline, sdk, rewriter, router, narrator, packs,
                 speaker, broadcast, settings: dict | None = None,
                 store: SessionStore | None = None, llm=None):
        self.pipeline = pipeline
        self.sdk = sdk
        self.rewriter = rewriter
        self.router = router
        self.narrator = narrator
        self.packs = packs
        self.speaker = speaker
        self.broadcast = broadcast            # async (dict) -> None
        self.settings = settings or load_settings()
        self.store = store or SessionStore()
        self.llm = llm
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
        self._need_resume = False            # 打开历史会话后首个任务先 resume
        # 当前会话
        self.session: dict = {}
        self._plan_mode = False
        self.compact_summary: str = ""
        # turn 跟踪（前端分组折叠 + 计时）
        self.turn_seq: int = 0
        self.turn_started_at: float = 0.0
        # 长期目标 {active, text, round, max_rounds}
        self.goal: dict = {"active": False, "text": "", "round": 0,
                           "max_rounds": 0}
        self._goal_pending = False   # 语音"制定目标"后等待目标文本
        # 声纹注册
        self.enroll_mode = False
        self.enroll_target = 3
        self.enroll_samples: list[np.ndarray] = []

    def bind_loop(self) -> None:
        self.loop = asyncio.get_running_loop()

    # ================================================== 线程→asyncio 桥
    def _from_thread(self, coro_factory) -> None:
        if self.loop and not self.loop.is_closed():
            def _runner():
                async def _safe():
                    try:
                        await coro_factory()
                    except Exception as e:  # 必须可见：任务链断裂用户要看到
                        import traceback
                        traceback.print_exc()
                        try:
                            await self.broadcast({"t": "error",
                                                  "message": f"{type(e).__name__}: {e}"})
                            await self.broadcast({"t": "msg", "role": "system",
                                                  "text": f"出错了：{e}", "tid": self.turn_seq})
                            if self.state not in ("idle", "shutdown"):
                                await self._set_state("idle")
                        except Exception:
                            pass
                return asyncio.create_task(_safe())
            self.loop.call_soon_threadsafe(_runner)

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
        await self.broadcast({"t": "msg", "role": "user", "text": text,
                                  "tid": self.turn_seq})
        self._log("user", text)
        if self.enroll_mode:
            return  # 注册模式只收音频
        if await self._try_voice_command(text):
            return
        if self._goal_pending:
            self._goal_pending = False
            await self._goal_start(text)
            return
        await self._dispatch(text)

    # ================================================== 语音命令触发
    @staticmethod
    def _match_voice_cmd(text: str, table: dict) -> tuple[str, list] | None:
        """关键词组匹配：归一化文本含组内全部词即命中，返回 (cmd, 组)。"""
        from server.voice.wake import normalize
        norm = normalize(text)
        for cmd, groups in table.items():
            for group in groups:
                if all(w in norm for w in group):
                    return cmd, group
        return None

    async def _try_voice_command(self, text: str) -> bool:
        """自然语言触发命令：'导出当前会话' → /export 等。"""
        from server.voice.wake import normalize
        table = (self.settings.get("slash_voice")
                 or load_settings().get("slash_voice", {}))
        hit = self._match_voice_cmd(text, table)
        if not hit:
            return False
        cmd, group = hit
        norm = normalize(text)
        tail = group[-1]
        rest = norm[norm.rfind(tail) + len(tail):].strip() if tail in norm else ""

        def _after(text_full: str) -> str:
            n = normalize(text_full)
            t = normalize(group[-1])
            i = n.rfind(t)
            return n[i + len(t):].strip() if i >= 0 else ""

        remainder = _after(text)
        if cmd == "export":
            await self._do_export()
        elif cmd == "compact":
            await self._do_compact()
        elif cmd == "goal_stop":
            await self._goal_stop()
        elif cmd == "goal":
            if len(remainder) >= 4:
                await self._goal_start(remainder)
            else:
                self._goal_pending = True
                self.narrator.confirm("好，请说出你的长期目标。")
                self.pipeline.arm_listening(30)
        elif cmd == "plan":
            if len(remainder) >= 4:
                await self.slash("plan", remainder)
            else:
                self.narrator.confirm("请说出要规划的内容。")
                self.pipeline.arm_listening(30)
        return True

    # ================================================== 斜杠命令
    PLAN_SUFFIX = (
        "\n\n（计划模式：本次任务只做分析与规划——不要创建、修改或删除任何文件，"
        "不要执行任何变更性命令；输出一份结构清晰、可执行的分步计划。）"
    )

    async def slash(self, cmd: str, arg: str) -> None:
        cmd = (cmd or "").strip().lstrip("/").lower()
        arg = (arg or "").strip()
        if cmd == "plan":
            if not arg:
                await self.broadcast({"t": "msg", "role": "system",
                                      "text": "用法：/plan <目标> —— 只规划不修改。", "tid": self.turn_seq})
                return
            self._plan_mode = True
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": "进入计划模式（只读规划，本轮生效）。", "tid": self.turn_seq})
            self.narrator.confirm("计划模式，只规划不修改。")
            self._log("system", "计划模式开启")
            await self.on_text_input(arg)
        elif cmd == "compact":
            await self._do_compact()
        elif cmd == "export":
            await self._do_export()
        elif cmd == "goal":
            if arg in ("stop", "停", "取消"):
                await self._goal_stop()
            elif arg:
                await self._goal_start(arg)
            else:
                await self.broadcast({"t": "msg", "role": "system",
                                      "text": "用法：/goal <长期目标> · /goal stop 停止", "tid": self.turn_seq})
        else:
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": f"未知命令 /{cmd}。可用：/plan /compact /export /goal", "tid": self.turn_seq})

    async def _do_export(self) -> None:
        await self.broadcast({"t": "trigger_export"})
        self.narrator.confirm("会话导出完成，文件已开始下载。")
        self._log("system", "导出会话")

    # ================================================== 长期目标
    async def _goal_start(self, text: str) -> None:
        s = load_settings()
        self.goal = {"active": True, "text": text, "round": 0,
                     "max_rounds": int(s.get("goal_max_rounds", 12))}
        await self.broadcast({"t": "msg", "role": "system",
                              "text": f"长期目标已设定（最多 {self.goal['max_rounds']} 轮）：{text}", "tid": self.turn_seq})
        self._log("system", f"目标设定：{text}")
        self.narrator.confirm(f"目标已设定，开始多轮推进：{text[:30]}。")
        if self.state == "exec":
            return  # 当前任务完成后自动接续
        await self._goal_next_round()

    async def _goal_stop(self, done: bool = False) -> None:
        if not self.goal.get("active"):
            return
        self.goal["active"] = False
        note = ("目标流程结束。" if done else "目标已停止。")
        await self.broadcast({"t": "msg", "role": "system", "text": note})
        self._log("system", note)
        self.narrator.confirm(note if done else "好，目标已停止。")

    async def _goal_next_round(self) -> None:
        if not self.goal.get("active"):
            return
        self.goal["round"] += 1
        r = self.goal["round"]
        prompt = (
            f"（长期目标推进 · 第 {r}/{self.goal['max_rounds']} 轮）\n"
            f"目标：{self.goal['text']}\n"
            f"请执行本轮可推进的具体工作。回复末尾必须单独一行输出："
            f"目标状态：已达成 或 目标状态：进行中"
        )
        await self.broadcast({"t": "msg", "role": "system",
                              "text": f"目标第 {r} 轮开始。", "tid": self.turn_seq})
        self.narrator.confirm(f"目标第 {r} 轮，推进中。")
        await self._start_task(prompt)

    def _goal_check(self) -> None:
        """轮末判定：达成/超限 → 结束。"""
        if not self.goal.get("active"):
            return
        text = self.last_assistant_text or ""
        done = ("已达成" in text) or self.goal["round"] >= self.goal["max_rounds"]
        if done:
            asyncio.create_task(self._goal_stop(done=True))

    async def _do_compact(self) -> None:
        """压缩上下文：LLM 总结 → 新 DSH 会话（本地记录保留）。"""
        if not self.transcript:
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": "会话还没有内容，无需压缩。", "tid": self.turn_seq})
            return
        await self.broadcast({"t": "msg", "role": "system", "text": "正在压缩上下文…"})
        text = "\n".join(f"{e.get('role')}: {(e.get('text') or '')[:200]}"
                         for e in self.transcript[-60:])
        summary = ""
        if self.llm is not None:
            try:
                summary = await self.llm.chat(
                    [{"role": "system",
                      "content": "把这段 Agent 会话记录压缩成不超过 150 字的摘要，"
                                 "保留目标、关键决定与未完成事项。只输出摘要。"},
                     {"role": "user", "content": text}],
                    max_tokens=300, temperature=0.2,
                    thinking="disabled", timeout=15.0)
                summary = (summary or "").strip()
            except Exception:
                summary = ""
        self.compact_summary = summary
        try:
            await self.sdk.stop()
        except Exception:
            pass
        self.sdk.reset_identity("")
        self._need_resume = False
        if self.session.get("id"):
            self.session["dsh_session_id"] = ""
            self.store.update(self.session["id"], {"dsh_session_id": ""})
        note = f"上下文已压缩（历史保留在本地）。摘要：{summary or '（生成失败，直接清空）'}"
        await self.broadcast({"t": "msg", "role": "system", "text": note})
        self._log("system", note)
        self.narrator.confirm("上下文已压缩。")
        await self._set_state("idle")

    # ================================================== 会话管理
    async def broadcast_sessions(self) -> None:
        await self.broadcast({"t": "sessions", "list": self.store.list(),
                              "current": self.session.get("id", "")})

    async def session_new(self) -> None:
        if self.state == "exec":
            self.narrator.confirm("任务还在执行，先等它结束或说暂停。")
            return
        try:
            await self.sdk.stop()   # 当前 DSH 会话已持久化
        except Exception:
            pass
        self.sdk.reset_identity("")
        self._need_resume = False
        self.session = self.store.create()
        self.transcript = []
        self.pending_prompts = []
        self.route_info = {}
        await self.broadcast({"t": "history", "msgs": []})
        await self.broadcast({"t": "session", "meta": self.session})
        await self.broadcast_sessions()

    async def session_open(self, sid: str) -> None:
        meta = self.store.get(sid)
        if not meta:
            return
        if self.state == "exec":
            self.narrator.confirm("任务还在执行，先等它结束或说暂停。")
            return
        try:
            await self.sdk.stop()
        except Exception:
            pass
        self.session = meta
        self.sdk.reset_identity(meta.get("dsh_session_id", ""))
        self._need_resume = bool(meta.get("dsh_session_id"))
        self.transcript = [
            {"role": e.get("role", ""), "text": e.get("text", ""),
             "ts": e.get("ts", 0)}
            for e in self.store.events(sid)
        ]
        self.pending_prompts = []
        await self.broadcast({"t": "history", "msgs": self.transcript})
        await self.broadcast({"t": "session", "meta": meta})
        await self.broadcast_sessions()
        self.narrator.confirm(f"已打开会话：{meta.get('title') or '未命名'}。")

    async def session_delete(self, sid: str) -> None:
        self.store.delete(sid)
        if self.session.get("id") == sid:
            await self.session_new()
        else:
            await self.broadcast_sessions()

    async def session_update(self, sid: str, patch: dict) -> None:
        meta = self.store.update(sid, patch)
        if not meta:
            return
        if self.session.get("id") == sid:
            self.session = meta
            # 工作区/权限变更：下次任务生效；运行中进程重启
            if ("cwd" in patch or "perm" in patch) and self.sdk.proc:
                self.sdk.pause()
                self._need_resume = bool(meta.get("dsh_session_id"))
        # 即时反馈：仅工作区/权限/重命名（模型选择静默——下拉自身即反馈）
        notes = []
        if "perm" in patch:
            notes.append(f"权限已切换：{patch['perm']}，下个任务生效")
        if "cwd" in patch:
            notes.append(f"工作区已切换：{patch['cwd']}")
        if "title" in patch:
            notes.append(f"会话已重命名：{patch['title']}")
        for note in notes:
            await self.broadcast({"t": "msg", "role": "system", "text": note})
            self._log("system", note)
        if notes:
            self.narrator.confirm(notes[0] + "。")
        await self.broadcast({"t": "session", "meta": meta})
        await self.broadcast_sessions()

    async def _gen_title(self, prompt: str) -> None:
        """首个任务后自动起会话名（≤10 字）。"""
        title = prompt[:12]
        if self.llm is not None:
            try:
                out = await self.llm.chat(
                    [{"role": "system",
                      "content": "给下面的任务起一个不超过10个字的会话标题，"
                                 "只输出标题本身。"},
                     {"role": "user", "content": prompt}],
                    max_tokens=32, temperature=0.3,
                    thinking="disabled", timeout=6.0)
                out = (out or "").strip().strip('"').strip('「」')
                if out and len(out) <= 16:
                    title = out
            except Exception:
                pass
        await self.session_update(self.session["id"], {"title": title})

    def _msg(self, role: str, text: str, extra: dict | None = None) -> None:
        """带 tid 的消息广播（前端按 turn 分组折叠）。"""
        ev = {"t": "msg", "role": role, "text": text, "tid": self.turn_seq}
        if extra:
            ev.update(extra)

        async def _send():
            await self.broadcast(ev)
        asyncio.create_task(_send())
        self._log(role, text)

    def _log(self, role: str, text: str) -> None:
        if self.session.get("id") and text:
            # 相邻去重：assistant 终稿与 task 总结常为同文
            last = getattr(self, "_last_log", None)
            if last == (role, text):
                return
            self._last_log = (role, text)
            try:
                self.store.append_event(self.session["id"], role, text)
            except Exception:
                pass

    # ================================================== 取消聆听
    async def cancel_listen(self) -> None:
        self.pipeline.standby()
        self.enroll_mode = False
        await self._set_state("idle")

    # ================================================== 手动语音输入
    async def manual_listen(self, seconds: float = 20.0) -> None:
        """唤醒词不可用时的兜底：直接进入聆听（跳过唤醒词与声纹——
        用户主动点击即明确意图）。执行中点击=语音插话（入队）。"""
        if self.enroll_mode or self.state in ("confirm_shutdown", "shutdown"):
            return
        self.pipeline.arm_listening(seconds)
        await self._set_state("listen")
        await self.broadcast({"t": "wake_ack", "accepted": True,
                              "speaker_ok": True, "score": -1.0,
                              "manual": True})

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
        if self._goal_pending:
            self._goal_pending = False
            await self.broadcast({"t": "msg", "role": "user", "text": text,
                                  "tid": self.turn_seq})
            await self._goal_start(text)
            return
        if await self._try_voice_command(text):
            return
        self.transcript.append({"role": "user", "text": text, "ts": time.time()})
        await self.broadcast({"t": "final", "text": text})
        await self.broadcast({"t": "msg", "role": "user", "text": text,
                                  "tid": self.turn_seq})
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
        self._log("system", f"改写 → {result.text}")
        await self._after_rewrite(result.text)

    async def _after_rewrite(self, prompt: str) -> None:
        """改写完成后的公共路径：路由 →（执行中入队 / 开新任务）。"""
        difficulty = await self.router.classify(prompt)
        # 现读磁盘设置：改模型不用重启服务
        route = self.router.route(difficulty)
        self.settings = load_settings()
        # 会话级模型覆盖（UI 下拉选择）
        override = (self.session or {}).get("model_override")
        if override:
            route = {**route, "model": override}
        self.route_info = route
        await self.broadcast({"t": "route", **route})
        # 自动模式才播报路由；手动选定时模型是用户决定的，不再报
        if not override:
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": f"路由：{route.get('model')} · {difficulty}", "tid": self.turn_seq})
            self._log("system", f"路由：{route.get('model')} · {difficulty}")

        if self.state == "exec":
            # 执行中插话：入队，turn 结束后送达
            self.pending_prompts.append(prompt)
            self.narrator.step("收到，记下了，当前任务完成后就做。")
            return

        await self._start_task(prompt)

    async def _start_task(self, prompt: str) -> None:
        if not self.session.get("id"):
            self.session = self.store.create()
        route = self.route_info or self.router.route("normal")
        if not self.sdk.proc:
            perm = self.session.get("perm")
            if self._plan_mode:
                perm = "read-only"   # 计划模式：硬约束只读
            await self.sdk.start(route["model"], route.get("reasoning_effort"),
                                 cwd=self.session.get("cwd"),
                                 permission=perm)
            if self._need_resume:
                try:
                    await self.sdk.resume(self.sdk.session_id)
                except Exception:
                    # 工作区已变更等原因导致历史不可续接：新开 DSH 会话
                    await self.broadcast({"t": "msg", "role": "system",
                                          "text": "历史会话无法在此工作区续接，已开启新对话上下文。", "tid": self.turn_seq})
                    self.sdk.reset_identity("")
                    await self.sdk.start(route["model"],
                                         route.get("reasoning_effort"),
                                         cwd=self.session.get("cwd"),
                                         permission=self.session.get("perm"))
                self._need_resume = False
            await self.broadcast({"t": "state", "s": "exec",
                                  "session": self.sdk.session_id})
            # 绑定/回填 dsh 会话 id，首个任务自动起名
            if not self.session.get("dsh_session_id"):
                self.session["dsh_session_id"] = self.sdk.session_id
                self.session["model"] = route.get("model") or ""
                self.store.upsert(self.session)
                if not self.session.get("title"):
                    asyncio.create_task(self._gen_title(prompt))
        else:
            await self.broadcast({"t": "state", "s": "exec"})
        self.state = "exec"
        self.current_brief = prompt[:40]
        self.turn_seq += 1
        self.turn_started_at = time.time()
        await self.broadcast({"t": "turn_start", "tid": self.turn_seq})
        self.narrator.speak("收到，开始。", prio=1, kind="confirm")
        self.transcript.append({"role": "task", "text": prompt,
                                "ts": time.time()})
        # 执行偏好（默认抑制滥用子代理；设置可关）
        s = self.settings
        suffix = ""
        if s.get("use_task_policy", True) and s.get("task_policy_suffix"):
            suffix = s["task_policy_suffix"]
        if self._plan_mode:
            suffix = self.PLAN_SUFFIX
        prompt_out = prompt
        persona = (self.settings.get("persona")
                   or load_settings().get("persona") or "").strip()
        if persona:
            prompt_out = f"（人设：{persona}）\n\n{prompt_out}"
        if self.compact_summary:
            prompt_out = f"（前情摘要：{self.compact_summary}）\n\n{prompt_out}"
        await self.sdk.prompt(prompt_out + suffix)
        self._plan_mode = False   # 计划模式单轮：prompt 已带约束，发起即复位

    # ================================================== SDK 通知
    REASONING_BLOCKS = ("reasoning", "thinking")

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
                btype = block.get("type", "")
                if btype in self.REASONING_BLOCKS:
                    piece = (block.get("text") or block.get("thinking")
                             or block.get("content") or "")
                    if piece:
                        await self.broadcast({"t": "thinking", "text": piece,
                                              "tid": self.turn_seq})
                elif btype == "text" and block.get("text", "").strip():
                    text = block["text"].strip()
                    self.last_assistant_text = text
                    await self.broadcast({"t": "thinking_end"})
                    await self.broadcast({"t": "msg", "role": "assistant",
                                          "text": text, "tid": self.turn_seq})
                    self._log("assistant", text)
                elif btype in ("tool_call", "tool_use"):
                    summary = self.narrator.tool_summary(
                        block.get("name", "tool"),
                        block.get("arguments") or block.get("input") or "")
                    await self.broadcast({"t": "msg", "role": "tool",
                                          "text": summary,
                                          "tid": self.turn_seq})
                    self._log("tool", summary)
        elif "reasoning" in typ or "thinking" in typ:
            piece = (data.get("text") or data.get("delta")
                     or data.get("content") or "")
            if piece:
                await self.broadcast({"t": "thinking", "text": piece,
                                      "tid": self.turn_seq})
        elif typ in ("tool/call", "tool/use"):
            summary = self.narrator.tool_summary(
                data.get("name") or data.get("tool") or "tool",
                data.get("arguments") or data.get("input")
                or data.get("args") or data.get("command") or "")
            await self.broadcast({"t": "msg", "role": "tool",
                                  "text": summary, "tid": self.turn_seq})
            self._log("tool", summary)
        elif typ == "tool/result":
            out = (data.get("result") or data.get("output") or "")
            if isinstance(out, str) and out.strip():
                await self.broadcast({"t": "msg", "role": "tool",
                                      "text": f"结果：{out.strip()[:120]}",
                                      "tid": self.turn_seq})
        await self.broadcast({"t": "step", "type": typ})
        self.narrator.on_agent_event(ev)
        if typ == "turn/end":
            self._turn_task = asyncio.create_task(self._turn_done())

    async def _turn_done(self) -> None:
        self._plan_mode = False   # 计划模式仅单轮生效
        summary = self.last_assistant_text[:200] or "任务执行完毕。"
        seconds = max(0, time.time() - self.turn_started_at)
        self.transcript.append({"role": "assistant", "text": summary,
                                "ts": time.time()})
        await self.broadcast({"t": "turn_done", "tid": self.turn_seq,
                              "summary": summary, "seconds": round(seconds)})
        self._log("assistant", summary)
        # 注意：最后一条 assistant 消息已由步骤播报（含压缩）呈现过，
        # 这里只播结束语——避免同内容双播双列（两个声音的根因）。
        nickname = self.settings.get("user_nickname", "")
        call = f"{nickname}，" if nickname else ""
        self.narrator.final(f"{call}任务完成，请指示。")
        await self._set_state("idle")
        if self.pending_prompts:
            nxt = self.pending_prompts.pop(0)
            await asyncio.sleep(1.0)
            await self._start_task(nxt)
            return
        if self.goal.get("active"):
            self._goal_check()
            if self.goal.get("active"):
                await asyncio.sleep(1.5)
                await self._goal_next_round()

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
                if not self.sdk.proc:
                    await self.sdk.start(route.get("model") or "glm-5.3-flash",
                                         route.get("reasoning_effort"),
                                         cwd=self.session.get("cwd"),
                                         permission=self.session.get("perm"))
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
