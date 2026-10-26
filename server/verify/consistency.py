"""L1: 语义一致性检查 — Agent 声明 vs 工具输出（ground truth）比对。"""

from __future__ import annotations

import re


CHECK_PROMPT = """你是事实核查员。对比 Agent 的声明和实际工具输出，找出矛盾。

Agent 声明：
{claims}

工具实际输出（ground truth）：
{ground_truth}

检查规则：
1. Agent 说"创建了 N 个文件" → 实际输出里是否真的有 N 个
2. Agent 说"测试通过" → 实际输出是否显示 pass/成功
3. Agent 说"修改了 X" → 实际输出是否有对应修改记录
4. Agent 说的数字、文件名、结果是否与实际一致

只输出 JSON：
{"contradictions": [{"claim": "...", "actual": "...", "severity": "high|medium|low"}], "confidence": 0.0-1.0}

如果没有矛盾，输出 {"contradictions": [], "confidence": 1.0}"""


async def run_l1(agent_summary: str, tool_outputs: list[str],
                 llm) -> dict | None:
    """L1 语义一致性检查。

    Args:
        agent_summary: Agent 的最终总结文本
        tool_outputs: 本次任务所有工具输出列表
        llm: LLM 客户端

    Returns:
        {"layer": 1, "type": "consistency",
         "contradictions": [...], "confidence": float}
        或 None（无 LLM 可用或出错）
    """
    if llm is None or not agent_summary:
        return None

    # 截断工具输出（避免 token 爆炸）
    ground_truth = "\n---\n".join(
        out[:500] for out in tool_outputs[:10])  # 最多10条，每条500字

    if not ground_truth.strip():
        return None  # 没有工具输出可比对

    try:
        import json
        out = await llm.chat(
            [{"role": "system",
              "content": CHECK_PROMPT.format(
                  claims=agent_summary[:800],
                  ground_truth=ground_truth)},
             {"role": "user", "content": "请检查"}],
            max_tokens=300, temperature=0.0,
            thinking="disabled", timeout=10.0)
        m = re.search(r'\{[\s\S]*?\}', out or "")
        if m:
            d = json.loads(m.group())
            contradictions = d.get("contradictions", [])
            confidence = float(d.get("confidence", 1.0))
            return {
                "layer": 1, "type": "consistency",
                "pass": len(contradictions) == 0,
                "contradictions": contradictions,
                "confidence": confidence,
                "detail": f"{len(contradictions)} 个矛盾" if contradictions
                          else f"一致（置信度 {confidence:.0%}）",
            }
    except Exception:
        pass
    return None
