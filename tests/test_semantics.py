"""总控语义机状态机单测（全替身，无模型/网络/进程）。"""
import asyncio
import json

import pytest

from server.agent.rewriter import RewriteResult
from server.agent.semantics import Semantics
from server.config import load_settings


class FakePipeline:
    def __init__(self):
        self.fed = b""
        self.tts_gate = None
        self.arm_called = 0
        self.settings = {}

    def feed_pcm(self, b):
        self.fed += b

    def set_tts_gate(self, on, hold=None):
        self.tts_gate = on

    def arm_listening(self, seconds=12):
        self.arm_called += 1

    def standby(self):
        self.arm_called = 0


class FakeSdk:
    def __init__(self):
        self.proc = None
        self.session_id = "sess-test-1"
        self.started_with = []
        self.prompts = []
        self.resumed = None
        self.paused = False
        self.stopped = False

    async def start(self, model, effort, max_tokens=None,
                    cwd=None, permission=None):
        self.started_with.append((model, effort))
        self.proc = object()  # 非 None 表示活着
        if not self.session_id:
            self.session_id = "sess-test-1"   # 与真实客户端一致的懒生成
        return self.session_id

    def reset_identity(self, session_id=""):
        self.session_id = session_id
        self.proc = None

    async def prompt(self, text, sid=None):
        self.prompts.append(text)
        return {"messageId": "m"}

    async def resume(self, sid):
        self.resumed = sid

    def pause(self):
        self.paused = True
        self.proc = None

    async def stop(self):
        self.stopped = True
        self.proc = None


class FakeNarrator:
    def __init__(self):
        self.said: list[tuple] = []
        self.history: list[str] = []
        self.speaking = False

    class _Q:
        def empty(self):
            return True

    q = _Q()

    def speak(self, text, prio=2, kind="step", dedup=False):
        self.said.append((kind, text))
        self.history.append(text)

    def step(self, t):
        self.speak(t, 2, "step", dedup=True)

    def final(self, t):
        self.speak(t, 0, "final")

    def confirm(self, t):
        self.speak(t, 1, "confirm")

    def on_agent_event(self, ev):
        pass


class FakePacks:
    def wake_phrase(self):
        return "在的，请讲。"

    def farewell_phrase(self):
        return "再见。"


class FakeRewriter:
    def __init__(self):
        self.finals = []

    async def prewarm(self, t, on_draft=None):
        pass

    async def finalize(self, t):
        self.finals.append(t)
        return RewriteResult("final", f"专业版：{t}")


class FakeRouter:
    async def classify(self, p):
        return "normal"

    def route(self, d, settings=None):
        return {"model": "glm-5.3", "reasoning_effort": None,
                "difficulty": d}


def make_sem(tmp_path, monkeypatch):
    events = []

    async def broadcast(ev):
        events.append(ev)

    # 隔离会话存储（防写真实 run/sessions.json）
    import server.sessions as S
    monkeypatch.setattr(S, "STORE_DIR", tmp_path / "sess")
    monkeypatch.setattr(S, "INDEX", tmp_path / "sess.json")
    store = S.SessionStore()

    pipeline, sdk, narrator = FakePipeline(), FakeSdk(), FakeNarrator()
    sem = Semantics(pipeline, sdk, FakeRewriter(), FakeRouter(), narrator,
                    FakePacks(), None, broadcast, load_settings(), store=store)
    # 存档与自停替身
    monkeypatch.setattr(sem, "_archive", lambda: tmp_path / "arch")
    monkeypatch.setattr(sem, "self_stop", lambda: events.append({"t": "_stopped"}))
    return sem, sdk, narrator, events


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- 基本流
def test_wake_to_listen(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem._wake("Hey, SPICA", True, 0.9))
    assert sem.state == "listen"
    assert narrator.said[0][1] == "在的，请讲。"
    assert any(e.get("t") == "wake_ack" for e in events)


def test_final_dispatches_task(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem._wake("嘿SPICA", True, 0.9))
    run(sem._final("帮我写个脚本统计目录大小"))
    assert sdk.started_with == [("glm-5.3", None)]   # 难度路由生效
    assert sdk.prompts and "专业版：帮我写个脚本统计目录大小" in sdk.prompts[0]
    assert sem.state == "exec"
    assert any(e.get("t") == "rewrite" and e.get("stage") == "final"
               for e in events)


def test_turn_done_back_to_idle_and_summary(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem._wake("嘿SPICA", True, 0.9))
    run(sem._final("做点东西"))
    run(sem.on_sdk_notification("session.event", {
        "event": {"type": "assistant/message",
                  "data": {"message": {"role": "assistant", "content": [
                      {"type": "text", "text": "已经完成了三件事。"}]}}}}))
    run(sem.on_sdk_notification("session.event", {
        "event": {"type": "turn/end", "data": {"reason": {"kind": "completed"}}}}))
    run(asyncio.sleep(0.05))
    assert sem.state == "idle"
    done = [e for e in events if e.get("t") == "turn_done"]
    assert done and done[0].get("tid") >= 1
    assert isinstance(done[0].get("seconds"), (int, float))
    # 任务结束完全静默（界面呈现完成态）
    assert not any("任务完成" in t for _, t in narrator.said)


# ---------------------------------------------------------------- 插话队列
def test_bargein_queues_prompt(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem._wake("嘿SPICA", True, 0.9))
    run(sem._final("第一个任务"))
    run(sem._final("第二个任务"))          # 执行中插话
    assert len(sdk.prompts) == 1           # 不打断当前
    assert sem.pending_prompts == ["专业版：第二个任务"]
    # turn 结束后自动派发
    # turn 结束后自动派发（与通知同循环，等待后台任务完成）
    async def scenario():
        await sem.on_sdk_notification("session.event", {
            "event": {"type": "turn/end", "data": {}}})
        await asyncio.sleep(1.2)   # _turn_done 内含 1s 缓冲
    run(scenario())
    assert len(sdk.prompts) == 2


# ---------------------------------------------------------------- 暂停/恢复
def test_pause_resume(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem._wake("嘿SPICA", True, 0.9))
    run(sem._final("长任务"))
    run(sem._command("pause", "暂停"))
    assert sdk.paused and sem.state == "paused"
    run(sem._command("resume", "继续"))
    assert sdk.resumed == "sess-test-1"
    assert "继续刚才的任务。" in sdk.prompts
    assert sem.state == "exec"


# ---------------------------------------------------------------- 声纹注册
class FakeSpeaker:
    def __init__(self):
        self.enrolled_with = None

    def enroll(self, samples):
        self.enrolled_with = samples
        return True


def test_enroll_flow_collects_and_finishes(tmp_path, monkeypatch):
    import numpy as np
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.speaker = FakeSpeaker()
    run(sem.enroll_start(3))
    assert sem.enroll_mode is True
    for _ in range(3):
        run(sem._segment_audio(np.zeros(16000 * 2, dtype=np.float32)))
    assert sem.enroll_mode is False
    assert len(sem.speaker.enrolled_with) == 3
    done = [e for e in events if e.get("t") == "diag"
            and e.get("enroll", {}).get("phase") == "done"]
    assert done and done[0]["enroll"]["ok"] is True
    assert sem.state == "idle"


def test_enroll_short_segment_rejected(tmp_path, monkeypatch):
    import numpy as np
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.speaker = FakeSpeaker()
    run(sem.enroll_start(3))
    run(sem._segment_audio(np.zeros(8000, dtype=np.float32)))  # 0.5s
    assert len(sem.enroll_samples) == 0
    assert any(e.get("t") == "diag" and e.get("enroll", {}).get("phase") == "too_short"
               for e in events)
    assert sem.enroll_mode is True


def test_enroll_period_no_tts_instructions(tmp_path, monkeypatch):
    """注册期间不发任何 TTS（防自采）：开始/进度全走界面事件。"""
    import numpy as np
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.speaker = FakeSpeaker()
    run(sem.enroll_start(3))
    assert narrator.said == []            # 开始注册：无语音
    run(sem._segment_audio(np.zeros(16000 * 2, dtype=np.float32)))
    assert narrator.said == []            # 收到第 1 段：无语音
    run(sem._segment_audio(np.zeros(16000 * 2, dtype=np.float32)))
    run(sem._segment_audio(np.zeros(16000 * 2, dtype=np.float32)))
    assert sem.enroll_mode is False
    # 注册全程静默（成功不播报，页面可见结果）
    assert narrator.said == []


# ---------------------------------------------------------------- 手动聆听
def test_manual_listen_enters_listen(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem.manual_listen())
    assert sem.state == "listen"
    ack = next(e for e in events if e.get("t") == "wake_ack")
    assert ack.get("manual") is True
    assert sem.pipeline.arm_called == 1


def test_manual_listen_blocked_in_confirm(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.state = "confirm_shutdown"
    run(sem.manual_listen())
    assert sem.state == "confirm_shutdown"   # 不被覆盖
    assert sem.pipeline.arm_called == 0


def test_manual_listen_blocked_in_enroll(tmp_path, monkeypatch):
    import numpy as np
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.speaker = FakeSpeaker()
    run(sem.enroll_start(3))
    run(sem.manual_listen())
    assert sem.pipeline.arm_called == 1      # 只有 enroll_start 那一次


# ---------------------------------------------------------------- 长期目标
def test_goal_multi_round(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem.slash("goal", "整理所有照片"))
    assert sem.goal["active"] and sem.goal["round"] == 1
    assert sdk.prompts and "整理所有照片" in sdk.prompts[-1]
    assert "第 1/12 轮" in sdk.prompts[-1]
    # 轮结束（进行中）→ 自动下一轮
    async def scenario():
        await sem.on_sdk_notification("session.event", {
            "event": {"type": "assistant/message",
                      "data": {"message": {"role": "assistant", "content": [
                          {"type": "text", "text": "本轮整理了 3 张。目标状态：进行中"}]}}}})
        await sem.on_sdk_notification("session.event", {
            "event": {"type": "turn/end", "data": {}}})
        await asyncio.sleep(1.8)   # 轮间隔
    run(scenario())
    assert sem.goal["round"] == 2
    assert len(sdk.prompts) == 2


def test_goal_finishes_when_done(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem.slash("goal", "小目标"))
    async def scenario():
        await sem.on_sdk_notification("session.event", {
            "event": {"type": "assistant/message",
                      "data": {"message": {"role": "assistant", "content": [
                          {"type": "text", "text": "全部完成。目标状态：已达成"}]}}}})
        await sem.on_sdk_notification("session.event", {
            "event": {"type": "turn/end", "data": {}}})
        await asyncio.sleep(0.3)
    run(scenario())
    assert sem.goal["active"] is False


def test_goal_stop(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem.slash("goal", "x"))
    run(sem.slash("goal", "stop"))
    assert sem.goal["active"] is False


# ---------------------------------------------------------------- 语音命令
def test_voice_command_export(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem._try_voice_command("帮我把当前会话导出一下"))
    assert any(e.get("t") == "trigger_export" for e in events)
    assert any("导出" in t for _, t in narrator.said)


def test_voice_command_compact(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.llm = FakeSlashLLM()
    run(sem.on_text_input("做个东西"))
    async def scenario():
        await sem._try_voice_command("压缩一下上下文")
        await asyncio.sleep(0.1)
    run(scenario())
    assert sdk.stopped
    assert sem.compact_summary == "压缩后的会话摘要"


def test_voice_command_goal_with_text(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem._try_voice_command("制定目标 把文档全部翻新一遍"))
    assert sem.goal["active"]
    assert "把文档全部翻新一遍" in sem.goal["text"]


def test_voice_command_goal_pending_then_text(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem._try_voice_command("制定目标"))
    assert sem._goal_pending is True
    run(sem.on_text_input("重做整个首页"))
    assert sem.goal["active"] and "重做整个首页" in sem.goal["text"]


def test_persona_prefix(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    import server.agent.semantics as sem_mod
    base = dict(sem.settings)
    monkeypatch.setattr(sem_mod, "load_settings",
                        lambda: {**base, "persona": "你是毒舌但专业的架构师"})
    sem.state = "idle"
    run(sem.on_text_input("看看代码结构"))
    assert "（用户人设：你是毒舌但专业的架构师）" in sdk.prompts[-1]
    assert "你是 SPICA" in sdk.prompts[-1]          # 身份也在前缀


# ---------------------------------------------------------------- 斜杠命令
class FakeSlashLLM:
    async def chat(self, messages, **kw):
        return "压缩后的会话摘要"


def test_slash_compact_resets_dsh(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.llm = FakeSlashLLM()
    run(sem.session_new())
    run(sem.on_text_input("做个东西"))
    run(sem.slash("compact", ""))
    assert sdk.stopped                       # DSH 上下文清零
    assert sem.compact_summary == "压缩后的会话摘要"
    assert any("上下文已压缩" in e.get("text", "") for e in events
               if e.get("t") == "msg")
    # 下个任务带前情摘要
    run(sem.on_text_input("继续"))
    assert sdk.prompts[-1].startswith("（前情摘要：压缩后的会话摘要）")


def test_slash_plan_sets_readonly_and_suffix(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.state = "idle"
    run(sem.slash("plan", "重构登录模块"))
    assert sem._plan_mode is False           # _start_task 已消费（单轮）
    assert sdk.prompts and "计划模式" in sdk.prompts[-1]
    assert "重构登录模块" in sdk.prompts[-1]


def test_slash_unknown(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem.slash("whatever", ""))
    assert any("未知命令" in e.get("text", "") for e in events
               if e.get("t") == "msg")


def test_model_override_shows_in_route(tmp_path, monkeypatch):
    """会话级模型覆盖：不输出路由消息（手动选定无需播报），模型实际生效。"""
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem.session_new())
    run(sem.on_text_input("自动模式任务"))
    assert any("路由" in e.get("text", "") for e in events
               if e.get("t") == "msg")          # 自动模式：有路由消息
    events.clear()
    run(sem.session_update(sem.session["id"], {"model_override": "glm-5.3"}))
    events.clear()
    run(sem.on_text_input("手动模式任务"))
    assert not any("路由" in e.get("text", "") for e in events
                   if e.get("t") == "msg")      # 手动模式：无路由消息
    assert sdk.started_with[-1][0] == "glm-5.3"  # 且模型确实生效


# ---------------------------------------------------------------- 权限升级
def test_perm_request_on_denied_tool(tmp_path, monkeypatch):
    import asyncio
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.state = "idle"
    run(sem.on_text_input("任务"))
    async def scenario():
        await sem.on_sdk_notification("session.event", {
            "event": {"type": "tool/result",
                      "data": {"result": "bash: /etc/hosts: Permission denied"}}})
        await asyncio.sleep(0.1)
    run(scenario())
    assert sem._perm_request is not None
    assert any(e.get("t") == "permission_request" for e in events)


def test_perm_grant_once_upgrades_and_resumes(tmp_path, monkeypatch):
    import asyncio
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem._perm_request = {"tid": 1, "reason": "denied"}
    async def scenario():
        await sem.grant_permission("once")
        await asyncio.sleep(0.2)
    run(scenario())
    assert sem._perm_request is None
    assert sdk.paused and sdk.resumed == "sess-test-1"
    assert "更高权限" in sdk.prompts[-1]
    assert sem.session.get("perm") != "danger-full-access"  # once 不持久化


def test_perm_grant_always_persists(tmp_path, monkeypatch):
    import asyncio
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem.session_new())
    sem._perm_request = {"tid": 1, "reason": "denied"}
    async def scenario():
        await sem.grant_permission("always")
        await asyncio.sleep(0.2)
    run(scenario())
    assert sem.session.get("perm") == "danger-full-access"


def test_perm_deny_notifies_agent(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.state = "idle"
    run(sem.on_text_input("任务"))
    sem._perm_request = {"tid": 1, "reason": "denied"}
    run(sem.grant_permission("deny"))
    assert "拒绝" in sdk.prompts[-1]


def test_perm_voice_answers(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem._perm_request = {"tid": 1, "reason": "denied"}
    run(sem._final("永远同意"))
    assert sem._perm_request is None
    assert any(e.get("t") == "permission_resolved"
               and e.get("mode") == "always" for e in events)


# ---------------------------------------------------------------- 键盘输入
def test_text_input_dispatches_without_rewrite(tmp_path, monkeypatch):
    """键盘输入：跳过改写、直接路由执行（FakeRewriter 不该被调用）。"""
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem.on_text_input("在 workspace 创建 README.md"))
    assert sem.rewriter.finals == []                      # 未走改写
    assert sdk.prompts and "在 workspace 创建 README.md" in sdk.prompts[0]
    assert any(e.get("t") == "msg" and e.get("role") == "user"
               for e in events)
    assert sem.state == "exec"


def test_text_input_queues_when_exec(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem.on_text_input("任务一"))
    run(sem.on_text_input("任务二"))
    assert len(sdk.prompts) == 1
    assert sem.pending_prompts == ["任务二"]


# ---------------------------------------------------------------- 结束词
def test_farewell_idle_shuts_down(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem._farewell("Bye, SPICA"))
    assert sdk.stopped
    assert any(e.get("t") == "_stopped" for e in events)
    assert any(e.get("t") == "shutdown" for e in events)


def test_farewell_exec_asks_confirm(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem._wake("嘿SPICA", True, 0.9))
    run(sem._final("任务"))
    run(sem._farewell("拜拜SPICA"))
    assert sem.state == "confirm_shutdown"
    assert not sdk.stopped                      # 未确认不关停
    run(sem._command("confirm", "确定"))
    assert any(e.get("t") == "_stopped" for e in events)


# ---------------------------------------------------------------- 会话残留修复
def test_delete_session_while_paused_no_leak(tmp_path, monkeypatch):
    """暂停任务→删除会话→新会话点继续：不得继续旧任务。"""
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    run(sem.on_text_input("旧会话任务A"))
    run(sem._command("pause", "暂停"))
    assert sem.state == "paused"
    sid = sem.session["id"]
    run(sem.session_delete(sid))          # 删除 → 自动 session_new
    assert sem.state == "idle"            # 状态已重置
    prompts_before = len(sdk.prompts)
    run(sem._command("resume", "继续"))   # 新会话里点继续
    # 不应重启 DSH 也不应注入"继续刚才的任务"
    assert "继续刚才的任务。" not in " ".join(sdk.prompts[prompts_before:])
    assert sem.state == "idle"


def test_diff_meta_edit_write():
    m = Semantics._diff_meta("edit", {"old_string": "a\nb\nc",
                                      "new_string": "x"})
    assert m == {"a": 1, "r": 3}
    m2 = Semantics._diff_meta("write", {"content": "l1\nl2\nl3"})
    assert m2 == {"a": 3, "r": 0}
    assert Semantics._diff_meta("bash", {"command": "ls"}) is None


def test_web_tool_counted_as_browse(tmp_path, monkeypatch):
    import asyncio
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.state = "idle"
    run(sem.on_text_input("查资料"))
    async def scenario():
        for u in ["https://a.com/1", "https://b.com/x"]:
            await sem.on_sdk_notification("session.event", {
                "event": {"type": "tool/call",
                          "data": {"name": "web_fetch", "arguments": {"url": u}}}})
        await sem.on_sdk_notification("session.event", {
            "event": {"type": "turn/end", "data": {}}})
        await asyncio.sleep(0.3)
    run(scenario())
    browses = [e for e in events if e.get("t") == "msg"
               and "浏览网页" in e.get("text", "")]
    assert len(browses) == 2
    done = next(e for e in events if e.get("t") == "turn_done")
    assert done.get("browsed") == 2


def test_perm_request_classify_and_explain(tmp_path, monkeypatch):
    import asyncio
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)

    class ExplainLLM:
        async def chat(self, m, **k):
            return "把测试域名加进本地解析"
    sem.llm = ExplainLLM()
    sem.state = "idle"
    run(sem.on_text_input("改hosts"))
    sem._last_tool = 'bash {"command": "echo \"127.0.0.1 test\" >> /etc/hosts"}'
    async def scenario():
        await sem.on_sdk_notification("session.event", {
            "event": {"type": "tool/result",
                      "data": {"result": "Permission denied"}}})
        await asyncio.sleep(0.1)
    run(scenario())
    req = next(e for e in events if e.get("t") == "permission_request")
    assert req["perm_type"] == "修改系统文件"
    assert req["action_desc"] == "把测试域名加进本地解析"
    assert "/etc/hosts" in req["detail"]


# ---------------------------------------------------------------- 闲聊分流
class ChatClassifyLLM:
    def __init__(self, chat_map, reply="我是SPICA，语音优先的本地助理。"):
        self.chat_map = chat_map
        self.reply = reply
    async def chat(self, messages, **kw):
        sys = messages[0]["content"]
        if "闲聊/问答" in sys:
            for k, v in self.chat_map.items():
                if k in messages[-1]["content"]:
                    return '{"chat": %s}' % ("true" if v else "false")
            return '{"chat": false}'
        return self.reply


def test_chat_short_circuits_dsh(tmp_path, monkeypatch):
    """"你是谁"→直接身份回复，不进 DSH 不喊"收到，开始"。"""
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.llm = ChatClassifyLLM({"你是谁": True})
    sem.state = "idle"
    prompts_before = len(sdk.prompts)
    run(sem.on_text_input("你是谁？"))
    assert len(sdk.prompts) == prompts_before          # 未走 DSH
    assert not any("收到" in t for _, t in narrator.said)
    reply = [e for e in events if e.get("t") == "msg"
             and e.get("role") == "assistant"]
    assert reply and "SPICA" in reply[-1]["text"]      # 身份回复入列
    assert any("SPICA" in t for _, t in narrator.said)  # 且播报


def test_task_still_routes_to_dsh(tmp_path, monkeypatch):
    sem, sdk, narrator, events = make_sem(tmp_path, monkeypatch)
    sem.llm = ChatClassifyLLM({"写个脚本": False})
    sem.state = "idle"
    run(sem.on_text_input("写个脚本统计目录"))
    assert sdk.prompts and "写个脚本" in sdk.prompts[-1]  # 走 DSH（前缀含身份）


def test_identity_override(tmp_path, monkeypatch):
    import server.agent.semantics as sem_mod
    from server.config import SPICA_IDENTITY, load_settings
    base = load_settings()
    monkeypatch.setattr(sem_mod, "load_settings",
                        lambda: {**base, "identity_override": "我是瓦力"})
    sem, _, _, _ = make_sem(tmp_path, monkeypatch)
    assert sem._identity_prompt().startswith("我是瓦力")
    monkeypatch.setattr(sem_mod, "load_settings", lambda: base)
    assert sem._identity_prompt().startswith("你是 SPICA")
    assert "DeepSeek Harness" in sem._identity_prompt()
    # 动态驱动模型：会话 override 优先
    sem.session["model_override"] = "glm-5.3"
    assert "由 glm-5.3 模型驱动" in sem._identity_prompt()
    del sem.session["model_override"]
    assert "由 glm-5.3-flash 模型驱动" in sem._identity_prompt("glm-5.3-flash")
