"""LLM 层单测（FakeLLM，不发真实请求）+ 可选真实冒烟（SPICA_LIVE=1）。"""
import asyncio
import os

import pytest

from server.agent.llm import LLMClient
from server.agent.rewriter import Rewriter, RewriteResult
from server.agent.router import Router


class FakeLLM(LLMClient):
    """按 system 关键词返回脚本化回复。"""

    def __init__(self, prewarm_reply="", finalize_reply="", classify_reply="",
                 error: Exception | None = None):
        self.prewarm_reply = prewarm_reply
        self.finalize_reply = finalize_reply
        self.classify_reply = classify_reply
        self.error = error
        self.calls: list[dict] = []

    async def chat(self, messages, model=None, max_tokens=None,
                   temperature=None, stream=False, timeout=60.0,
                   thinking=None):
        self.calls.append({"system": messages[0]["content"],
                           "user": messages[-1]["content"],
                           "model": model, "thinking": thinking})
        if self.error:
            raise self.error
        sys = messages[0]["content"]
        if "校对" in sys:
            return self.finalize_reply
        if "难度" in sys:
            return self.classify_reply
        return self.prewarm_reply


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------- 改写器
def test_prewarm_produces_draft():
    llm = FakeLLM(prewarm_reply="帮我编写一个 Python 脚本统计目录大小")
    r = Rewriter(llm, debounce_ms=10)
    drafts: list[RewriteResult] = []

    async def scenario():
        await r.prewarm("帮我写个python脚本统计目录大小", on_draft=drafts.append)
        if r._task:
            await r._task

    run(scenario())
    assert r.draft == "帮我编写一个 Python 脚本统计目录大小"
    assert drafts and drafts[0].stage == "draft"


def test_finalize_uses_draft_as_context():
    llm = FakeLLM(prewarm_reply="草稿A", finalize_reply="最终版")
    r = Rewriter(llm, debounce_ms=10)
    r.draft = "草稿A"
    out = run(r.finalize("完整终稿转写"))
    assert out.text == "最终版" and out.stage == "final"
    # 校对 prompt 应同时含草稿与终稿
    user = llm.calls[-1]["user"]
    assert "草稿A" in user and "完整终稿转写" in user
    assert "校对" in llm.calls[-1]["system"]


def test_finalize_dropped():
    llm = FakeLLM(finalize_reply="丢弃")
    r = Rewriter(llm, debounce_ms=10)
    out = run(r.finalize("嗯啊啊那个"))
    assert out.dropped and out.text == ""


def test_finalize_llm_failure_falls_back_to_transcript():
    llm = FakeLLM(error=RuntimeError("network down"))
    r = Rewriter(llm, debounce_ms=10)
    out = run(r.finalize("直接用这句转写"))
    assert out.text == "直接用这句转写"


def test_short_input_dropped():
    llm = FakeLLM()
    r = Rewriter(llm, debounce_ms=10)
    out = run(r.finalize("好"))
    assert out.dropped


# ---------------------------------------------------------------- 路由
def test_router_classify_parses():
    llm = FakeLLM(classify_reply='{"difficulty":"complex"}')
    assert run(Router(llm).classify("设计一个多Agent调度系统")) == "complex"


def test_router_classify_fallback_on_garbage():
    llm = FakeLLM(classify_reply="我认为这是简单任务")
    assert run(Router(llm).classify("查一下日期")) == "normal"


def test_router_route_mapping():
    settings = {"difficulty_routes": {
        "simple": {"model": "glm-5.3", "reasoning_effort": "low"},
        "normal": {"model": "glm-5.3", "reasoning_effort": None},
        "complex": {"model": "glm-5.3", "reasoning_effort": "max"},
    }}
    r = Router(FakeLLM())
    assert r.route("simple", settings) == {
        "model": "glm-5.3", "reasoning_effort": "low", "difficulty": "simple"}
    assert r.route("unknown", settings)["difficulty"] == "normal"  # 未知级回退


# ---------------------------------------------------------------- 真实冒烟（可选）
@pytest.mark.skipif(os.environ.get("SPICA_LIVE") != "1",
                    reason="需要真实 zai 凭据；SPICA_LIVE=1 启用")
def test_live_llm_smoke():
    llm = LLMClient()
    assert llm.ready, "未找到 ZAI_CODING_CN_API_KEY"
    out = run(llm.chat([{"role": "user", "content": "只回复两个字：好的"}],
                       max_tokens=64, thinking="disabled"))
    assert "好的" in out
