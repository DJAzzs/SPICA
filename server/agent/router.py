"""难度路由：一次廉价 LLM 调用分级 → DSH 初始化参数映射。

分级 → settings.difficulty_routes = {
  simple:  {model, reasoning_effort},
  normal:  {...},
  complex: {...},
}
reasoning_effort 即 DSH SDK InitializeParams.reasoningEffort
（adapter-owned 标识符；None 表示省略用模型默认）。
"""
from __future__ import annotations

import json
import re

from server.agent.llm import LLMClient

ROUTER_SYSTEM = (
    "判断下面这条给编码 Agent 的任务提示词的难度，只输出一个 JSON："
    '{"difficulty":"simple|normal|complex"}。'
    "标准：闲聊/单文件小改/一次性查询=simple；多文件改动、需规划=normal；"
    "架构设计/调试疑难/长链路任务=complex。"
)


class Router:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or LLMClient()

    async def classify(self, prompt: str) -> str:
        try:
            reply = await self.llm.chat(  # type: ignore[union-attr]
                [{"role": "system", "content": ROUTER_SYSTEM},
                 {"role": "user", "content": prompt}],
                model=None,
                max_tokens=64,
                temperature=0.0,
                timeout=15.0,
                thinking="disabled",
            )
            m = re.search(r'"difficulty"\s*:\s*"(simple|normal|complex)"', reply or "")
            if m:
                return m.group(1)
        except Exception:
            pass
        return "normal"  # 失败保守取 normal

    def route(self, difficulty: str, settings: dict | None = None) -> dict:
        from server.config import load_settings
        s = settings or load_settings()
        routes = s.get("difficulty_routes", {})
        if difficulty not in routes:
            difficulty = "normal"
        r = routes.get(difficulty) or {}
        return {
            "model": r.get("model"),
            "reasoning_effort": r.get("reasoning_effort"),
            "difficulty": difficulty,
        }
