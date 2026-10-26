"""总控语义机：管线回调 / WS 消息 → 状态流转 → SDK 任务 / 播报 / 关停。

状态：idle → listen →(final+rewrite+route)→ exec →(turn/end)→ idle
      exec ←→ paused（SIGTERM/重启+resume）
      任意 → confirm_shutdown →（确认）→ shutdown
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from server import lifecycle
from server.config import (ARCHIVES_DIR, ROOT, WORKSPACE_DIR, load_settings,
                           save_settings)
from server.evolution.memory import MemoryStore
from server.evolution.skills import SkillStore
from server.sessions import PERMS, SessionStore
from server.tts.narrator import Narrator

CONFIRM_WINDOW_S = 20.0

# 工具结果中的权限拒绝特征
import re as _re
_PERM_DENIED = _re.compile(
    r"permission denied|EACCES|operation not permitted|read-only "
    r"filesystem|权限不足|没有权限", _re.I)


class Semantics:
    def __init__(self, pipeline, sdk, rewriter, router, narrator, packs,
                 speaker, broadcast, settings: dict | None = None,
                 store: SessionStore | None = None, llm=None,
                 memory_store=None, skill_store=None):
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
        # 权限升级请求 {tid, reason}；None=无待决
        self._perm_request: dict | None = None
        # 自进化
        self.memory_store = memory_store or MemoryStore()
        self.skill_store = skill_store or SkillStore(
            Path(self.settings.get("skill_root", "")) if self.settings.get("skill_root")
            else ROOT / "workspace" / "skills")
        self._turn_count = 0          # nudge 节拍
        self._turn_tool_calls = 0     # 本轮工具调用数（技能收获启发）
        self._turn_web_count = 0
        self._last_tool = ""          # 最近工具调用摘要（权限解释用）
        # 运行统计（tokens/上下文/速度）
        self._turn_files: dict[str, dict] = {}   # path -> {a, r}
        self._stats = {"total_in": 0, "total_out": 0, "ctx_win": 0,
                       "ctx_used": 0, "turns": 0, "steps": 0,
                       "last_speed": 0.0}
        self._step_started_at = 0.0
        self._compacting = False
        self._ctx_breakdown: dict = {}
        # 运行统计（tokens/上下文/速度）
        self._turn_files: dict[str, dict] = {}   # path -> {a, r}
        self._stats = {"total_in": 0, "total_out": 0, "ctx_win": 0,
                       "ctx_used": 0, "turns": 0, "steps": 0,
                       "last_speed": 0.0}
        self._step_started_at = 0.0
        self._compacting = False
        self._ctx_breakdown: dict = {}
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
        if self._perm_request:
            mode = self._try_perm_voice(text)
            if mode:
                await self.grant_permission(mode)
                return
        intent = await self._classify_intent(text)
        if intent["intent"] == "chat":
            self._log("user", text)
            await self._chat_reply(text)
            return
        if intent["intent"] == "music_play":
            self._log("user", text)
            await self.music_play(intent.get("query", text)[:40], source="voice")
            return
        if intent["intent"] == "music_stop":
            await self.music_stop(quiet=False)
            return
        if intent["intent"] == "pause":
            await self._command("pause", text)
            return
        if intent["intent"] == "resume":
            await self._command("resume", text)
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
        elif cmd == "music_play":
            await self.music_play(remainder[:40], source="voice")
        elif cmd == "music_stop":
            await self.music_stop(quiet=False)
        elif cmd == "memory_add" and rest:
            ok, msg = self.memory_store.add("memory", rest, source="voice")
            if ok:
                await self.broadcast({"t": "msg", "role": "system",
                                      "text": f"🧠 已记住：{rest[:60]}"})
                self.narrator.confirm("已记住。")
            else:
                self.narrator.confirm(msg)
        elif cmd == "compact":
            await self._do_compact()
        elif cmd == "goal_stop":
            await self._goal_stop()
        elif cmd == "music":
            parts = arg.split(None, 1)
            sub = parts[0].lower() if parts else "play"
            q = parts[1].strip() if len(parts) > 1 else ""
            if sub in ("stop", "off"):
                await self.music_stop()
            elif sub == "pause":
                await self.broadcast({"t": "music_ctrl", "action": "pause"})
            elif sub == "resume":
                await self.broadcast({"t": "music_ctrl", "action": "resume"})
            elif sub == "next":
                await self.broadcast({"t": "music_ctrl", "action": "next"})
            elif sub == "taste":
                from server.media.taste import MusicTaste
                await self.broadcast({"t": "msg", "role": "system",
                    "text": "〔音乐偏好〕" + MusicTaste().summary()})
            else:
                await self.music_play(q)
        elif cmd == "memory":
            await self.memory_command(arg)
        elif cmd == "skills":
            await self.skills_command(arg)
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


    def _bg(self, coro, tag: str) -> None:
        """fire-and-forget 且异常可见（自进化等后台动作）。"""
        async def _run():
            try:
                print(f"[evo] {tag} start", flush=True)
                await coro
                print(f"[evo] {tag} done", flush=True)
            except Exception:
                import traceback
                print(f"[evo] {tag} FAILED:", flush=True)
                traceback.print_exc()
        asyncio.create_task(_run())

    # ================================================== 自进化
    NUDGE_SYSTEM = (
        "你是记忆管家。根据本轮对话，判断是否有值得持久化的内容："
        "用户偏好/沟通风格（target=user）、环境事实/项目约定/踩坑教训"
        "（target=memory）。只输出 JSON：{\"save\":false} 或 "
        "{\"save\":true,\"target\":\"memory|user\",\"entry\":\"高信息密度的一句话条目\"}。"
        "琐碎、可网搜到、临时性的内容一律不保存。"
    )
    HARVEST_SYSTEM = (
        "你是技能提炼器。判断这轮 Agent 工作是否包含可复用的非平凡工作流"
        "（多步骤方法、踩坑后的正确解法、用户纠正过的流程）。只输出 JSON："
        "{\"harvest\":false} 或 "
        "{\"harvest\":true,\"name\":\"短名\",\"description\":\"一句话\","
        "\"when_to_use\":\"触发场景\",\"steps\":\"1. …\n2. …\","
        "\"pitfalls\":\"已知坑\",\"verify\":\"如何核验\"}。"
        "常规任务不要硬提炼。"
    )

    def _recent_events(self, n: int) -> str:
        """最近会话事件（含 tool 过程）——harvest/nudge 的输入源。"""
        sid = self.session.get("id")
        evs = self.store.events(sid) if sid else self.transcript
        return "\n".join(
            f"[{e.get('role')}] {(e.get('text') or '')[:160]}"
            for e in evs[-n:])

    async def _evolution_nudge(self) -> None:
        """每 5 轮：自动提炼值得记住的内容写入记忆（全自动+审计）。"""
        recent = self._recent_events(16)
        if not recent.strip():
            return
        try:
            import json as _json
            out = await self.llm.chat(
                [{"role": "system", "content": self.NUDGE_SYSTEM},
                 {"role": "user", "content": recent}],
                max_tokens=200, temperature=0.2,
                thinking="disabled", timeout=12.0)
            m = re.search(r"\{[\s\S]*\}", out or "")
            if not m:
                return
            d = _json.loads(m.group(0))
            if d.get("save") and d.get("entry"):
                target = d.get("target") if d.get("target") in ("memory", "user") \
                    else "memory"
                ok, msg = self.memory_store.add(
                    target, str(d["entry"]).strip(), source="nudge")
                if ok:
                    await self.broadcast({"t": "msg", "role": "system",
                        "text": f"🧠 已记住（{target}）：{str(d['entry'])[:60]}"})
        except Exception:
            pass

    async def _evolution_harvest(self, tools_used: int) -> None:
        """复杂任务（≥5 工具调用）成功后：自动提炼技能入库。"""
        recent = self._recent_events(20)
        try:
            import json as _json
            out = await self.llm.chat(
                [{"role": "system", "content": self.HARVEST_SYSTEM},
                 {"role": "user",
                  "content": f"本轮工具调用 {tools_used} 次。\n{recent}"}],
                max_tokens=500, temperature=0.2,
                thinking="disabled", timeout=15.0)
            m = re.search(r"\{[\s\S]*\}", out or "")
            if not m:
                return
            d = _json.loads(m.group(0))
            if not d.get("harvest"):
                return
            name = str(d.get("name", "")).strip()
            if not name:
                return
            p = self.skill_store.upsert(
                name, desc=str(d.get("description", "")),
                when=str(d.get("when_to_use", "")),
                steps=str(d.get("steps", "")),
                pitfalls=str(d.get("pitfalls", "无")),
                verify=str(d.get("verify", "")))
            if p:
                await self.broadcast({"t": "msg", "role": "system",
                    "text": f"🎓 自动学会技能《{name}》（下个任务起可复用；"
                            f"/skills 可查看或删除）"})
                self.narrator.step(f"学会了新技能：{name}。")
        except Exception:
            pass

    async def memory_command(self, arg: str) -> None:
        """/memory list | add <内容> | remove <子串> | user <内容>"""
        parts = (arg or "").split(None, 1)
        sub = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""
        if sub == "list":
            for kind in ("memory", "user"):
                es = self.memory_store.entries(kind)
                await self.broadcast({"t": "msg", "role": "system",
                    "text": f"〔{kind}〕(" + str(len(es)) + " 条)\n" +
                            ("\n§ ".join(es) if es else "（空）")})
        elif sub == "add" and rest:
            ok, msg = self.memory_store.add("memory", rest)
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": f"{msg}（memory）" if ok else f"失败：{msg}"})
        elif sub == "user" and rest:
            ok, msg = self.memory_store.add("user", rest)
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": f"{msg}（user）" if ok else f"失败：{msg}"})
        elif sub == "remove" and rest:
            for kind in ("memory", "user"):
                ok, msg = self.memory_store.remove(kind, rest)
                if ok:
                    await self.broadcast({"t": "msg", "role": "system",
                                          "text": msg})
                    return
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": f"未找到：{msg}"})
        else:
            await self.broadcast({"t": "msg", "role": "system",
                "text": "用法：/memory list · /memory add <内容> · "
                        "/memory user <偏好> · /memory remove <子串>"})

    async def skills_command(self, arg: str) -> None:
        """/skills list | del <名称>"""
        parts = (arg or "").split(None, 1)
        sub = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""
        if sub == "list":
            items = self.skill_store.list()
            if not items:
                await self.broadcast({"t": "msg", "role": "system",
                                      "text": "技能库为空——复杂任务成功后会自动学习。"})
                return
            lines = [f"- {s['name']}：{s['when'] or s['desc']}" for s in items]
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": "〔技能库〕\n" + "\n".join(lines)})
        elif sub in ("del", "delete", "rm") and rest:
            ok = self.skill_store.delete(rest)
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": f"已删除技能：{rest}" if ok
                                          else f"未找到技能：{rest}"})
        else:
            await self.broadcast({"t": "msg", "role": "system",
                "text": "用法：/skills list · /skills del <名称>"})

    # ================================================== 身份与闲聊
    def _current_model(self) -> str:
        """当前驱动模型：会话手动选择 > 最近任务路由 > 服务默认。"""
        return (self.session.get("model_override")
                or (self.route_info or {}).get("model")
                or load_settings().get("llm_model_rewrite")
                or "glm-5.3-flash")

    @staticmethod
    def _time_context() -> str:
        """当前时间（含星期、时段），注入 prompt 让 Agent 有时间观念。"""
        from datetime import datetime
        now = datetime.now()
        weekdays = ["一","二","三","四","五","六","日"]
        hour = now.hour
        if hour < 6: period = "深夜"
        elif hour < 9: period = "早晨"
        elif hour < 12: period = "上午"
        elif hour < 14: period = "中午"
        elif hour < 18: period = "下午"
        elif hour < 22: period = "晚上"
        else: period = "深夜"
        return (f"当前时间：{now.year}年{now.month}月{now.day}日 "
                f"星期{weekdays[now.weekday()]} {now.strftime('%H:%M')}（{period}）")

    def _identity_prompt(self, model: str | None = None) -> str:
        from server.config import SPICA_IDENTITY
        m = model or self._current_model()
        override = (load_settings().get("identity_override") or "").strip()
        ident = override if override else SPICA_IDENTITY.replace("{model}", m)
        persona = (load_settings().get("persona") or "").strip()
        out = ident + (f"\n（用户人设：{persona}）" if persona else "")
        return out + f"\n（{self._time_context()}）"

    CHAT_CLASSIFY_SYSTEM = (
        "判断用户输入是【闲聊/问答】还是【需要执行的任务】。"
        "闲聊：问候、关于你自身的问题、常识问答、简单讨论、一句话翻译。"
        "任务：需要写代码、操作文件、联网查询、多步执行、修改任何东西。"
        "只输出 JSON：{\"chat\": true} 或 {\"chat\": false}"
    )

    INTENT_SYSTEM = (
        "判断用户输入的意图。返回 JSON（只输出 JSON）：\n"
        '{"intent": "chat"} —— 闲聊、问答、关于你自身、讨论\n'
        '{"intent": "task"} —— 需要执行的任务（写代码、操作文件、搜索资料、多步操作）\n'
        '{"intent": "music_play", "query": "搜索词"} —— 播放音乐（提取歌名/歌手/风格）\n'
        '{"intent": "music_stop"} —— 停止/关闭音乐\n'
        '{"intent": "pause"} —— 暂停当前任务（等一下/先停/等等/稍等）\n'
        '{"intent": "resume"} —— 继续任务\n'
        '{"intent": "export"} —— 导出会话\n'
        '{"intent": "compact"} —— 压缩上下文\n'
        '{"intent": "memory_add", "content": "要记住的内容"} —— 记住某事\n'
        "示例：\n"
        '"放一首周杰伦的晴天" → {"intent": "music_play", "query": "周杰伦 晴天"}\n'
        '"来点BGM" → {"intent": "music_play", "query": ""}\n'
        '"等一下先别跑" → {"intent": "pause"}\n'
        '"你好呀" → {"intent": "chat"}\n'
        '"帮我看下这个代码" → {"intent": "task"}'
    )

    async def _classify_intent(self, text: str) -> dict:
        """统一意图分类：chat/task/music/pause/resume/export/compact/memory。"""
        if self.llm is None:
            return {"intent": "task"}  # 无 LLM 时全部走任务
        try:
            out = await self.llm.chat(
                [{"role": "system", "content": self.INTENT_SYSTEM},
                 {"role": "user", "content": text[:300]}],
                max_tokens=80, temperature=0.0,
                thinking="disabled", timeout=6.0)
            import json as _json
            m = re.search(r"\{[\s\S]*?\}", out or "")
            if m:
                d = _json.loads(m.group())
                return {"intent": d.get("intent", "chat"),
                        **({"query": d.get("query", "")} if d.get("query") else {}),
                        **({"content": d.get("content", "")} if d.get("content") else {})}
        except Exception:
            pass
        return {"intent": "task"}  # 解析失败走任务（安全兜底）

    async def _is_chat(self, text: str) -> bool:
        """廉价分类：闲聊直接回复，任务走完整管线。"""
        if self.llm is None:
            return False
        try:
            out = await self.llm.chat(
                [{"role": "system", "content": self.CHAT_CLASSIFY_SYSTEM},
                 {"role": "user", "content": text[:200]}],
                max_tokens=24, temperature=0.0,
                thinking="disabled", timeout=6.0)
            m = re.search(r'"chat"\s*:\s*(true|false)', out or "")
            return bool(m and m.group(1) == "true")
        except Exception:
            return False

    async def _chat_reply(self, text: str) -> None:
        """闲聊：身份+记忆直接回复，不走 DSH。"""
        mem_snap = "\n".join(x for x in (
            self.memory_store.render("memory"),
            self.memory_store.render("user")) if x)
        try:
            reply = await self.llm.chat(
                [{"role": "system",
                  "content": self._identity_prompt()
                  + ("\n" + mem_snap if mem_snap else "")},
                 {"role": "user", "content": text}],
                max_tokens=300, temperature=0.6,
                thinking="disabled", timeout=15.0)
        except Exception as e:
            reply = f"（回复失败：{e}）"
        reply = (reply or "").strip()
        await self.broadcast({"t": "msg", "role": "assistant", "text": reply})
        self._log("assistant", reply)
        self.narrator.step(reply)

    async def _send_initial_stats(self) -> None:
        """连接/切换会话时立即广播当前统计（底边栏常显）。"""
        await self._broadcast_stats()

    async def _broadcast_stats(self) -> None:
        s = self._stats
        pct = (s["ctx_used"] / s["ctx_win"] * 100) if s["ctx_win"] else 0
        await self.broadcast({"t": "stats",
            "total_in": s["total_in"], "total_out": s["total_out"],
            "total": s["total_in"] + s["total_out"],
            "ctx_pct": round(pct, 1), "ctx_win": s["ctx_win"],
            "ctx_used": s["ctx_used"],
            "turns": s["turns"], "steps": s["steps"],
            "speed": s["last_speed"],
            **({"breakdown": self._ctx_breakdown}
               if self._ctx_breakdown else {})})
        if pct >= 90 and not self._compacting:
            self._compacting = True
            self._bg(self._auto_compact(), "auto-compact")

    # ================================================== 工具过程美化
    @staticmethod
    def _diff_meta(name: str, args) -> dict | None:
        """edit/write 工具的 +/- 行数（无对应项不显示）。"""
        try:
            a = args if isinstance(args, dict) else {}
            if not a and isinstance(args, str) and args.strip().startswith("{"):
                import json as _j
                a = _j.loads(args)
            if name in ("edit", "str_replace_editor"):
                old, new = a.get("old_string", ""), a.get("new_string", "")
                if a.get("command") == "create" or old == "" and new:
                    return {"a": len(str(new).splitlines()) or 1, "r": 0}
                if not old and not new:
                    return None
                return {"a": len(str(new).splitlines()),
                        "r": len(str(old).splitlines())}
            if name == "write":
                return {"a": len(str(a.get("content", "")).splitlines()) or 1,
                        "r": 0}
        except Exception:
            pass
        return None

    @staticmethod
    def _tool_path(name: str, args) -> str:
        """从工具参数提取文件路径（edit/write/file tools）。"""
        try:
            a = args if isinstance(args, dict) else {}
            if not a and isinstance(args, str) and args.strip().startswith("{"):
                import json as _j
                a = _j.loads(args)
            for k in ("file_path", "path", "filename", "filePath"):
                if a.get(k):
                    return str(a[k])
        except Exception:
            pass
        return ""

    @staticmethod
    def _web_host(args) -> str:
        try:
            a = args if isinstance(args, dict) else {}
            url = str(a.get("url", ""))
            if "//" in url:
                return url.split("//", 1)[1].split("/", 1)[0][:40]
        except Exception:
            pass
        return ""

    # ================================================== 权限升级请求
    PERM_VOICE = [
        ("always", [["永远", "同意"], ["总是", "同意"], ["都", "同意"], ["全部", "允许"]]),
        ("deny", [["拒绝"], ["不允许"], ["不同意"], ["不要", "给"]]),
        ("once", [["同意"], ["允许"], ["可以"], ["给它", "权限"]]),
    ]

    @staticmethod
    def _perm_classify(detail: str) -> str:
        s = detail.lower()
        if re.search(r"/etc|/usr/bin|/sys|/boot|chmod|chown", s):
            return "修改系统文件"
        if re.search(r"apt|yum|dnf|pacman|systemctl|sudo", s):
            return "安装软件 / 系统管理"
        if re.search(r"\brm\b|delete|unlink|drop", s):
            return "删除文件"
        if re.search(r"write|>>|tee|echo.*>", s):
            return "写入工作区外的文件"
        return "访问受限资源"

    async def _request_permission(self, reason: str) -> None:
        """Agent 操作被权限拒绝 → 对话卡（人话解释）+ 语音请求授权。"""
        detail = (self._last_tool + " → " + reason).strip(" →")
        perm_type = self._perm_classify(detail)
        action_desc = ""
        if self.llm is not None and self._last_tool:
            try:
                action_desc = await self.llm.chat(
                    [{"role": "system",
                      "content": "用不超过 30 个字的日常中文解释这条命令想做什么"
                                 "（面向非技术用户，说目的不说术语）。只输出解释。"},
                     {"role": "user", "content": self._last_tool[:180]}],
                    max_tokens=64, temperature=0.3,
                    thinking="disabled", timeout=8.0)
                action_desc = (action_desc or "").strip()
            except Exception:
                action_desc = ""
        self._perm_request = {"tid": self.turn_seq, "reason": reason,
                              "perm_type": perm_type,
                              "action_desc": action_desc, "detail": detail}
        await self.broadcast({"t": "permission_request", "reason": reason,
                              "perm_type": perm_type,
                              "action_desc": action_desc, "detail": detail,
                              "tid": self.turn_seq})
        self.narrator.confirm(f"需要{perm_type}权限，"
                              f"{action_desc or 'Agent 的一次受限操作'}。同意吗？")
        self.pipeline.arm_listening(30)

    async def grant_permission(self, mode: str) -> None:
        """mode: once | always | deny。once/always 重启进程提权并续跑。"""
        req = self._perm_request
        self._perm_request = None
        if not req:
            return
        await self.broadcast({"t": "permission_resolved", "mode": mode})
        if mode == "deny":
            if self.sdk.proc:
                try:
                    await self.sdk.prompt("用户拒绝了权限提升。请在当前权限范围内"
                                          "换一种方式完成该步骤。")
                except Exception:
                    pass
            self.narrator.confirm("已拒绝。")
            return
        perm = "danger-full-access"
        if mode == "always" and self.session.get("id"):
            self.store.update(self.session["id"], {"perm": perm})
            self.session["perm"] = perm
        self.narrator.confirm("权限已提升，继续。")
        # 以更高权限重启 DSH 会话并续跑（会话已持久化）
        route = self.route_info or {}
        try:
            self.sdk.pause()
        except Exception:
            pass
        async def _resume():
            await self.sdk.start(route.get("model") or "glm-5.3-flash",
                                 route.get("reasoning_effort"),
                                 cwd=self.session.get("cwd"),
                                 permission=perm)
            await self.sdk.resume(self.sdk.session_id)
            await self.sdk.prompt(
                "用户已授权更高权限。请继续刚才的任务，重试因权限失败的操作。")
        self._bg(_resume(), "perm-upgrade")

    def _try_perm_voice(self, text: str) -> str | None:
        """权限请求期间的语音应答：once/always/deny。"""
        from server.voice.wake import normalize
        n = normalize(text)
        for mode, groups in self.PERM_VOICE:
            for group in groups:
                if all(w in n for w in group):
                    return mode
        return None

    # ================================================== 音乐（MusicFree/OpenSubsonic）
    async def music_play(self, query: str, source: str = "manual") -> None:
        """搜索并播放：描述/歌名→远程搜（空则 LLM 具体化）；无词→偏好加权推荐。"""
        from server.media.musicfree import MusicFree
        from server.media.taste import MusicTaste
        ok, info = await MusicFree.ping()
        if not ok:
            await self.broadcast({"t": "msg", "role": "system",
                "text": f"音乐服务未连接（{info[:60]}）。请在设置中配置 MusicFree 服务器地址与 API Key。"})
            self.narrator.confirm("音乐服务没有连上，请先在设置里配置。")
            return
        taste = MusicTaste()
        query = (query or "").strip()
        explored = False
        if query:
            keyword = query
            track = await MusicFree.pick(keyword)
            if not track and self.llm is not None:
                # 描述性查询（“英文摇滚”）搜不到 → LLM 翻译成具体歌名
                track = await self._describe_to_track(query)
        else:
            keyword, explored = taste.suggest()
            track = await MusicFree.pick(keyword)
        if not track:
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": f"没有找到「{keyword}」相关的歌。"})
            return
        taste.record(keyword, track.get("title", ""), track.get("artist", ""))
        await self.broadcast({"t": "music_track", **track})
        self._log("system", f"播放音乐：{track['title']} — {track['artist']}")
        if source == "voice":
            self.narrator.confirm(f"好，来听{track['title']}。")

    async def _describe_to_track(self, desc: str):
        """风格描述 → LMB 具体歌名 → 逐一尝试。"""
        from server.media.musicfree import MusicFree
        try:
            out = await self.llm.chat(
                [{"role": "system",
                  "content": "把音乐风格描述翻译成 3 个具体的『歌手 歌名』候选"
                                 "（真实存在的歌，贴合描述），JSON 数组，只输出数组。"},
                 {"role": "user", "content": desc[:60]}],
                max_tokens=150, temperature=0.6,
                thinking="disabled", timeout=10.0)
            m = re.search(r"\[[\s\S]*\]", out or "")
            if not m:
                return None
            import json as _json
            for name in _json.loads(m.group(0))[:3]:
                track = await MusicFree.pick(str(name))
                if track:
                    return track
        except Exception:
            pass
        return None

    async def music_stop(self, quiet: bool = False) -> None:
        await self.broadcast({"t": "music_stop"})
        if not quiet:
            self.narrator.confirm("音乐已停。")

    async def music_auto_pick(self, brief: str) -> None:
        """任务开始时自动配乐：flash 依据任务气质选关键词。"""
        if not load_settings().get("music_auto_on_task"):
            return
        keyword = "轻音乐"
        if self.llm is not None:
            try:
                out = await self.llm.chat(
                    [{"role": "system",
                      "content": "根据任务内容给一个音乐搜索关键词（4-10字，"
                                 "如『专注电子』『轻快钢琴』『city pop』）。只输出关键词。"},
                     {"role": "user", "content": brief[:120]}],
                    max_tokens=32, temperature=0.5,
                    thinking="disabled", timeout=6.0)
                k = (out or "").strip().strip('"')[:16]
                if k:
                    keyword = k
            except Exception:
                pass
        await self.music_play(keyword, source="auto")

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
        elif cmd == "music":
            parts = arg.split(None, 1)
            sub = parts[0].lower() if parts else "play"
            q = parts[1].strip() if len(parts) > 1 else ""
            if sub in ("stop", "off"):
                await self.music_stop()
            elif sub == "pause":
                await self.broadcast({"t": "music_ctrl", "action": "pause"})
            elif sub == "resume":
                await self.broadcast({"t": "music_ctrl", "action": "resume"})
            elif sub == "next":
                await self.broadcast({"t": "music_ctrl", "action": "next"})
            elif sub == "taste":
                from server.media.taste import MusicTaste
                await self.broadcast({"t": "msg", "role": "system",
                    "text": "〔音乐偏好〕" + MusicTaste().summary()})
            else:
                await self.music_play(q)
        elif cmd == "memory":
            await self.memory_command(arg)
        elif cmd == "skills":
            await self.skills_command(arg)
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
        self.narrator.confirm("目标已设定，开始推进。")
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
        self.narrator.confirm("目标已达成。" if done else "目标已停止。")

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
        from server.dsh_sessions import scan_dsh_sessions
        spica = self.store.list()
        # 合并 DSH 原生会话（排除 SPICA 自己创建的重复项）
        spica_ds_ids = {s.get("dsh_session_id") for s in spica
                        if s.get("dsh_session_id")}
        dsh = [d for d in scan_dsh_sessions()
               if d["id"] not in spica_ds_ids]
        merged = spica + dsh
        await self.broadcast({"t": "sessions", "list": merged,
                              "current": self.session.get("id", "")})

    async def session_new(self, cwd: str = "", perm: str = "") -> None:
        if self.state == "exec":
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": "任务执行中，结束后再切换会话。"})
            return
        try:
            await self.sdk.stop()   # 当前 DSH 会话已持久化
        except Exception:
            pass
        self.sdk.reset_identity("")
        self._need_resume = False
        self.session = self.store.create()
        if cwd:
            self.session = self.store.update(self.session["id"],
                {"cwd": cwd, **({"perm": perm} if perm else {})})
        # 彻底重置执行状态：旧会话的暂停/插话/目标不得泄漏到新会话
        if self.state not in ("shutdown",):
            self.state = "idle"
        self.transcript = []
        self.pending_prompts = []
        self.route_info = {}
        self._perm_request = None
        self._plan_mode = False
        self._goal_pending = False
        self.compact_summary = ""
        self.goal["active"] = False
        await self.broadcast({"t": "history", "msgs": []})
        self._bg(self._send_initial_stats(), "stats-init")
        await self.broadcast({"t": "session", "meta": self.session})
        await self.broadcast_sessions()

    async def session_open(self, sid: str) -> None:
        meta = self.store.get(sid)
        if not meta:
            # 尝试从 DSH 会话导入
            from server.dsh_sessions import scan_dsh_sessions
            dsh = next((d for d in scan_dsh_sessions() if d["id"] == sid), None)
            if dsh:
                meta = self.store.create(cwd=dsh["cwd"], perm=dsh.get("perm", "workspace-write"))
                meta["title"] = dsh["title"]
                meta["dsh_session_id"] = dsh["dsh_session_id"]
                meta["model"] = dsh.get("model", "")
                self.store.upsert(meta)
            else:
                return
        if self.state == "exec":
            await self.broadcast({"t": "msg", "role": "system",
                                  "text": "任务执行中，结束后再切换会话。"})
            return
        try:
            await self.sdk.stop()
        except Exception:
            pass
        self.session = meta
        self.sdk.reset_identity(meta.get("dsh_session_id", ""))
        self._need_resume = bool(meta.get("dsh_session_id"))

        # 优先读 SPICA 自己的事件；空则读 DSH 原生历史
        events = self.store.events(sid)
        if not events and meta.get("dsh_session_id"):
            from server.dsh_sessions import read_dsh_history
            events = read_dsh_history(meta["dsh_session_id"])

        # DSH 会话：继承统计（读取原会话 usage）
        if meta.get("dsh_session_id"):
            self._inherit_dsh_stats(meta["dsh_session_id"])
        self.transcript = [
            {"role": e.get("role", ""), "text": e.get("text", ""),
             "ts": e.get("ts", 0)}
            for e in events
        ]
        self.pending_prompts = []
        await self.broadcast({"t": "history", "msgs": self.transcript})
        await self.broadcast({"t": "session", "meta": meta})
        await self.broadcast_sessions()
        self._bg(self._send_initial_stats(), "stats-open")

    async def session_delete(self, sid: str) -> None:
        # 读取元数据（含 dsh_session_id）
        meta = self.store.get(sid)
        self.store.delete(sid)
        # 同时删除 DSH 会话文件
        dsh_id = (meta or {}).get("dsh_session_id") or (
            sid if sid.startswith(("session-", "spica-")) else "")
        if dsh_id:
            import shutil as _shutil
            dsh_root = Path.home() / ".dsh" / "sessions"
            if dsh_root.exists():
                for ws in dsh_root.iterdir():
                    d = ws / dsh_id
                    if d.exists():
                        try:
                            _shutil.rmtree(d)
                        except Exception:
                            pass
        # 清缓存
        from server.dsh_sessions import scan_dsh_sessions
        scan_dsh_sessions(force=True)
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

        for note in notes:
            await self.broadcast({"t": "msg", "role": "system", "text": note})
            self._log("system", note)
        await self.broadcast({"t": "session", "meta": meta})
        await self.broadcast_sessions()

    async def _gen_title(self, prompt: str) -> None:
        """首个任务后自动起会话名（≤10 字）。"""
        title = prompt[:14] + ("…" if len(prompt) > 14 else "")
        if self.llm is not None:
            try:
                out = await self.llm.chat(
                    [{"role": "system",
                      "content": "给下面的任务起一个 6-12 字的完整短语作为会话标题，"
                                 "只输出标题本身，不要截断。"},
                     {"role": "user", "content": prompt}],
                    max_tokens=32, temperature=0.3,
                    thinking="disabled", timeout=10.0)
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
        intent = await self._classify_intent(text)
        if intent["intent"] == "chat":
            self._log("user", text)
            await self.broadcast({"t": "msg", "role": "user", "text": text})
            await self._chat_reply(text)
            return
        if intent["intent"] == "music_play":
            self._log("user", text)
            await self.broadcast({"t": "msg", "role": "user", "text": text})
            await self.music_play(intent.get("query", text)[:40])
            return
        if intent["intent"] == "music_stop":
            await self.music_stop(quiet=False)
            return
        if intent["intent"] == "pause":
            await self._command("pause", text)
            return
        if intent["intent"] == "resume":
            await self._command("resume", text)
            return
        if intent["intent"] == "export":
            await self._do_export()
            return
        if intent["intent"] == "compact":
            await self._do_compact()
            return
        if intent["intent"] == "memory_add" and intent.get("content"):
            ok, msg = self.memory_store.add("memory", intent["content"], source="text")
            if ok:
                await self.broadcast({"t": "msg", "role": "system",
                                      "text": f"🧠 已记住：{intent['content'][:60]}"})
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
        # 会话级模型覆盖 + 思考深度覆盖（UI 下拉选择）
        override = (self.session or {}).get("model_override")
        if override:
            route = {**route, "model": override}
        effort_override = (self.session or {}).get("reasoning_effort_override")
        if effort_override and override:
            route = {**route, "reasoning_effort": effort_override}
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
        self._turn_files = {}
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
        # 身份+人设前缀（含动态驱动模型）
        prompt_out = f"{self._identity_prompt(route.get('model'))}\n\n{prompt_out}"
        # 自进化记忆快照（冻结注入，有界）
        mem_snap = "\n".join(x for x in (
            self.memory_store.render("memory"),
            self.memory_store.render("user")) if x)
        if mem_snap:
            prompt_out = f"{mem_snap}\n\n{prompt_out}"
        if self.compact_summary:
            prompt_out = f"（前情摘要：{self.compact_summary}）\n\n{prompt_out}"
        # 技能索引（渐进披露 L0：全文 Agent 按需 read）
        skill_idx = self.skill_store.render_index()
        if skill_idx:
            suffix = f"\n\n{skill_idx}" + suffix
        await self.sdk.prompt(prompt_out + suffix)
        self._plan_mode = False   # 计划模式单轮：prompt 已带约束，发起即复位
        self._bg(self.music_auto_pick(prompt[:80]), "music-auto")

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
                    name = block.get("name", "tool")
                    args = block.get("arguments") or block.get("input") or ""
                    if name in ("web_fetch", "web_search", "websearch"):
                        host = self._web_host(args)
                        summary = f"浏览网页{('：' + host) if host else ''}"
                        self._turn_web_count += 1
                    else:
                        summary = self.narrator.tool_summary(name, args)
                    ev = {"t": "msg", "role": "tool", "text": summary,
                          "tid": self.turn_seq}
                    d = self._diff_meta(name, args)
                    if d:
                        ev["diff"] = d
                        # 累计到 per-turn 文件变更表
                        fpath = self._tool_path(name, args)
                        if fpath:
                            cur = self._turn_files.get(fpath, {"a": 0, "r": 0})
                            cur["a"] += d.get("a", 0)
                            cur["r"] += d.get("r", 0)
                            self._turn_files[fpath] = cur
                    await self.broadcast(ev)
                    self._log("tool", summary)
        elif "reasoning" in typ or "thinking" in typ:
            piece = (data.get("text") or data.get("delta")
                     or data.get("content") or "")
            if piece:
                await self.broadcast({"t": "thinking", "text": piece,
                                      "tid": self.turn_seq})
        elif typ in ("tool/call", "tool/use"):
            name = data.get("name") or data.get("tool") or "tool"
            args = (data.get("arguments") or data.get("input")
                    or data.get("args") or data.get("command") or "")
            if name in ("web_fetch", "web_search", "websearch"):
                host = self._web_host(args)
                summary = f"浏览网页{('：' + host) if host else ''}"
                self._turn_web_count += 1
            elif name == "todo_write":
                # Todo List 实时同步到前端
                try:
                    import json as _json
                    if isinstance(args, str):
                        td = _json.loads(args)
                    else:
                        td = args
                    todos = td.get("todos") or td.get("todos") or []
                    if todos:
                        self._bg(self.broadcast({"t": "todo",
                            "todos": todos}), "todo")
                        summary = f"📋 更新任务清单（{len(todos)} 项）"
                    else:
                        summary = "📋 任务清单"
                except Exception:
                    summary = "📋 任务清单"
            else:
                summary = self.narrator.tool_summary(name, args)
            ev = {"t": "msg", "role": "tool", "text": summary,
                  "tid": self.turn_seq}
            d = self._diff_meta(name, args)
            if d:
                ev["diff"] = d
            await self.broadcast(ev)
            self._log("tool", summary)
        elif typ == "tool/result":
            out = (data.get("result") or data.get("output") or "")
            if isinstance(out, str) and out.strip():
                await self.broadcast({"t": "msg", "role": "tool",
                                      "text": f"结果：{out.strip()[:120]}",
                                      "tid": self.turn_seq})
                if self._perm_request is None and _PERM_DENIED.search(out):
                    await self._request_permission(out.strip()[:200])
        if typ == "step/start":
            self._step_started_at = time.time()
        elif typ == "step/end":
            u = data.get("usage") or {}
            self._stats["total_in"] += u.get("inputTokens", 0)
            self._stats["total_out"] += u.get("outputTokens", 0)
            self._stats["ctx_used"] = u.get("totalTokens",
                                            self._stats["ctx_used"])
            self._stats["steps"] += 1
            elapsed = time.time() - self._step_started_at
            if elapsed > 0.3 and u.get("outputTokens", 0) > 0:
                self._stats["last_speed"] = round(
                    u["outputTokens"] / elapsed, 1)
            asyncio.create_task(self._broadcast_stats())
        elif typ == "request/context":
            self._stats["ctx_win"] = data.get("contextWindow",
                                              self._stats["ctx_win"])
            # 上下文分解（系统提示/工具/消息）
            for key in ("systemPrompt", "toolDefinitions", "messages",
                        "conversation", "turns", "other"):
                if key in data:
                    self._ctx_breakdown[key] = data[key]
        if typ in ("tool/call", "tool/use") or "tool_call" in str(
                (data.get("message", {}) or {}).get("content", "")):
            self._turn_tool_calls += 1
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
        # 文件变更摘要（按总变更行数降序）
        cwd = self.session.get("cwd", "")
        files_sorted = sorted(
            self._turn_files.items(),
            key=lambda kv: -(kv[1]["a"] + kv[1]["r"]))
        files = [{
            "path": p.replace(cwd + "/", "") if cwd and p.startswith(cwd + "/") else p,
            "rel": bool(cwd and p.startswith(cwd + "/")),
            "a": v["a"], "r": v["r"],
        } for p, v in files_sorted if v["a"] > 0 or v["r"] > 0]
        await self.broadcast({"t": "turn_done", "tid": self.turn_seq,
                              "summary": summary, "seconds": round(seconds),
                              "browsed": self._turn_web_count,
                              "files": files})
        self._turn_web_count = 0
        self._stats["turns"] += 1
        self._log("assistant", summary)
        # 任务结束不再语音播报（完成态由界面呈现）
        await self._set_state("idle")
        # 自进化：计数 nudge + 复杂任务收获技能（全自动，异步不阻塞）
        self._turn_count += 1
        tools_used = self._turn_tool_calls
        self._turn_tool_calls = 0
        if self.state == "idle" and self.llm is not None:
            if self._turn_count % 5 == 0:
                self._bg(self._evolution_nudge(), f"nudge(turn={self._turn_count})")
            if tools_used >= 5:
                self._bg(self._evolution_harvest(tools_used),
                         f"harvest(tools={tools_used})")
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

    def _inherit_dsh_stats(self, dsh_id: str) -> None:
        """从 DSH 会话文件继承 token/context 统计。"""
        import subprocess as _sp
        from pathlib import Path as _P
        dsh_dir = _P.home() / ".dsh" / "sessions"
        for ws in dsh_dir.iterdir() if dsh_dir.exists() else []:
            zstd = ws / dsh_id / "session.v4.jsonl.zstd"
            if not zstd.exists():
                continue
            try:
                out = _sp.run(["zstdcat", "-q", str(zstd)],
                              capture_output=True, text=True, timeout=10)
                total_in = total_out = ctx_used = steps = turns = 0
                ctx_win = 0
                for line in out.stdout.splitlines():
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    d = e.get("data") or {}
                    if e.get("type") == "step/end":
                        u = d.get("usage") or {}
                        total_in += u.get("inputTokens", 0)
                        total_out += u.get("outputTokens", 0)
                        ctx_used = u.get("totalTokens", ctx_used)
                        steps += 1
                    elif e.get("type") == "turn/end":
                        turns += 1
                    elif e.get("type") == "request/context":
                        ctx_win = d.get("contextWindow", ctx_win)
                if total_in + total_out > 0:
                    self._stats.update({
                        "total_in": total_in, "total_out": total_out,
                        "ctx_used": ctx_used, "ctx_win": ctx_win,
                        "turns": turns, "steps": steps})
                    self._bg(self._broadcast_stats(), "inherit-stats")
            except Exception:
                pass
            break

    async def _auto_compact(self) -> None:
        """Context >=90% auto-compact (waits for current task to finish)."""
        try:
            for _ in range(120):
                if self.state not in ("exec", "paused"):
                    break
                await asyncio.sleep(1)
            if self.state in ("exec", "paused"):
                return
            await self._do_compact()
        finally:
            self._compacting = False
        self._ctx_breakdown: dict = {}

    async def _command(self, name: str, text: str) -> None:
        if name == "pause":
            if self.state == "exec":
                self.sdk.pause()
                self.narrator.confirm("已暂停。")
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
        # 注册完成不播报（页面可见结果）；失败才出声提醒
        if not ok:
            self.narrator.confirm("注册失败，请重试。")
        await self._set_state("idle")
