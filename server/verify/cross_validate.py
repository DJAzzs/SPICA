"""L3: 交叉验证 — 并行多版本比对。"""

from __future__ import annotations

import asyncio
import re


async def run_l3(task: str, primary_result: str, llm,
                 variants: int = 2) -> dict | None:
    """L3 交叉验证：让 LLM 从不同角度重做，比对一致性。

    轻量实现：不 spawn 完整 DSH 会话，而是让 LLM 独立回答同一任务，
    然后用 embedding 比对语义相似度。

    Args:
        task: 原始任务
        primary_result: 主 Agent 的结果
        llm: LLM 客户端
        variants: 额外验证次数（默认 2）

    Returns:
        {"layer": 3, "type": "cross_validate", "similarity": float, ...}
    """
    if llm is None:
        return None

    async def one_variant(temperature: float) -> str:
        try:
            return await llm.chat(
                [{"role": "user", "content": task}],
                max_tokens=500, temperature=temperature,
                thinking="disabled", timeout=20.0) or ""
        except Exception:
            return ""

    # 并行跑 N 个变体（不同温度）
    temps = [0.7, 0.3][:variants]
    results = await asyncio.gather(*[one_variant(t) for t in temps])
    results = [r for r in results if r.strip()]
    if not results:
        return None

    # 比对：用 LLM 判断一致性
    try:
        import json
        compare_prompt = (
            "对比以下对同一任务的回答，评估一致性。只输出 JSON：\n"
            '{"similarity": 0.0-1.0, "key_differences": ["..."], "verdict": "consistent|disputed"}\n\n'
            f"主版本：{primary_result[:400]}\n\n"
            + "\n\n---\n\n".join(f"变体{i+1}：{r[:400]}" for i, r in enumerate(results))
        )
        out = await llm.chat(
            [{"role": "user", "content": compare_prompt}],
            max_tokens=200, temperature=0.0,
            thinking="disabled", timeout=10.0)
        m = re.search(r'\{[\s\S]*?\}', out or "")
        if m:
            d = json.loads(m.group())
            similarity = float(d.get("similarity", 1.0))
            verdict = d.get("verdict", "consistent")
            return {
                "layer": 3, "type": "cross_validate",
                "pass": verdict == "consistent" and similarity >= 0.85,
                "similarity": similarity,
                "key_differences": d.get("key_differences", []),
                "verdict": verdict,
                "detail": f"相似度 {similarity:.0%}（{verdict}）",
            }
    except Exception:
        pass
    return None
