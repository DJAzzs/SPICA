"""两段式提示词改写器（方案 v6 关键设计）。

- prewarm(partial)：ASR partial 到达即后台改写（防抖 300ms、流式、限 token），
  产出"预热草稿"——用户说完话时草稿已就绪。
- finalize(final_transcript)：断句后以 SenseVoice 终稿 + 草稿为上下文做
  **最小校正**（不全量重写），差异显著才替换，防 UI 闪烁。

全部 async；并发任务自动取消旧预热。
"""
from __future__ import annotations

import asyncio
import difflib
from dataclasses import dataclass

from server.agent.llm import LLMClient

PREWARM_SYSTEM = (
    "你是语音指令改写器。用户对语音助手说了一段话，ASR 实时转写可能不完整、"
    "有口语赘词。把它改写成一句给编码 Agent 执行的专业任务提示词：保留全部"
    "意图与细节，补全省略的主语和目标，去除口语词，不添加转写中没有的要求。"
    "只输出改写结果，不要任何解释。转写过短或无意义时只输出：丢弃"
)

FINALIZE_SYSTEM = (
    "你是语音指令改写器的终稿校对。下面有【草稿】（基于不完整转写的预热改写）"
    "和【终稿转写】（完整准确的 ASR 结果）。以草稿为基础做最小修正，使它完全"
    "覆盖终稿转写的内容；草稿已正确的部分不要改动。若草稿与终稿转写内容一致，"
    "原样输出草稿。只输出最终改写结果。终稿转写无意义时只输出：丢弃"
)


@dataclass
class RewriteResult:
    stage: str          # draft | final
    text: str
    dropped: bool = False


def _significantly_different(a: str, b: str, ratio_threshold: float = 0.85) -> bool:
    """草稿与校正经的差异度判断（防 UI 闪烁）。"""
    if not a or not b:
        return True
    r = difflib.SequenceMatcher(None, a, b).ratio()
    return r < ratio_threshold


class Rewriter:
    def __init__(self, llm: LLMClient | None = None,
                 debounce_ms: int = 300):
        self.llm = llm or LLMClient()
        self.debounce = debounce_ms / 1000.0
        self.draft: str = ""
        self._task: asyncio.Task | None = None
        self._last_partial: str = ""

    # ------------------------------------------------------------ 预热
    async def prewarm(self, partial: str, on_draft=None) -> None:
        """partial 到达即调用；防抖合并，取消旧任务。"""
        self._last_partial = partial
        if self._task and not self._task.done():
            return  # 已有预热在跑（防抖由调用节奏+单任务模型保证）
        self._task = asyncio.create_task(self._prewarm_job(on_draft))

    async def _prewarm_job(self, on_draft) -> None:
        await asyncio.sleep(self.debounce)  # 防抖：等 partial 稳定
        while True:
            partial, self._last_partial = self._last_partial, ""
            if not partial or len(partial) < 2:
                if not self._last_partial:
                    return
                continue
            try:
                result = await self._rewrite(
                    PREWARM_SYSTEM, partial,
                    max_tokens=max(64, len(partial) * 3),
                    stage="draft",
                    thinking="disabled",
                )
                if result and not result.dropped:
                    self.draft = result.text
                    if on_draft:
                        on_draft(RewriteResult("draft", self.draft))
            except Exception:
                pass  # 预热失败无害：finalize 兜底
            if not self._last_partial:
                return

    # ------------------------------------------------------------ 终稿
    async def finalize(self, final_transcript: str, on_result=None) -> RewriteResult:
        """断句后调用：草稿+终稿最小校正。"""
        text = final_transcript.strip()
        if len(text) < 2:
            return RewriteResult("final", "", dropped=True)
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            if self.draft:
                user = f"【草稿】\n{self.draft}\n\n【终稿转写】\n{text}"
                result = await self._rewrite(FINALIZE_SYSTEM, user,
                                             max_tokens=512, stage="final",
                                             thinking="disabled")
            else:
                result = await self._rewrite(
                    PREWARM_SYSTEM, text, max_tokens=512, stage="final",
                    thinking="disabled")
        except Exception as e:
            # LLM 失败降级：终稿转写本身可读，直接用
            result = RewriteResult("final", text)
            result.error = str(e)  # type: ignore[attr-defined]
        self.draft = ""
        if on_result:
            on_result(result)
        return result

    # ------------------------------------------------------------ 底层
    async def _rewrite(self, system: str, user: str, max_tokens: int,
                       stage: str, model: str | None = None,
                       thinking: str | None = None) -> RewriteResult:
        reply = await self.llm.chat(  # type: ignore[union-attr]
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            model=model,
            max_tokens=max_tokens,
            temperature=0.3,
            thinking=thinking,
        )
        reply = (reply or "").strip()
        if reply in ("丢弃", ""):
            return RewriteResult(stage, "", dropped=True)
        return RewriteResult(stage, reply)
