"""L2: 对抗审查 — 独立 DSH 会话用不同模型找缺陷。"""

from __future__ import annotations

REVIEW_PROMPT = """你是对抗审查者。你的职责是找出以下工作中的缺陷、遗漏和潜在风险。

原始任务：
{task}

执行者的操作记录：
{actions}

执行者的结论：
{conclusion}

请从以下角度审查：
1. 任务是否真正完成（而非部分完成）
2. 是否有遗漏的边界情况
3. 是否有安全隐患
4. 代码质量（如有代码修改）
5. 结论是否被数据支撑

只输出 JSON：
{{"issues": [
  {{"severity": "high|medium|low", "description": "问题描述", "suggestion": "修复建议"}}
], "overall": "PASS|WARN|FAIL"}}

标准：high = 必须修复才能交付；medium = 建议修复；low = 可以接受。"""


async def run_l2(task: str, actions: list[str], conclusion: str,
                 llm) -> dict | None:
    """L2 对抗审查（轻量版：直接用 LLM 而非 DSH 会话，避免开销过大）。

    Args:
        task: 原始任务文本
        actions: 执行者的操作摘要列表
        conclusion: Agent 的最终结论
        llm: LLM 客户端（用不同模型避免同源偏差）

    Returns:
        {"layer": 2, "type": "adversarial", "issues": [...], "overall": str}
    """
    if llm is None:
        return None

    actions_text = "\n".join(f"- {a[:200]}" for a in actions[:20])
    if not actions_text:
        actions_text = "（无操作记录）"

    try:
        import json
        import re
        out = await llm.chat(
            [{"role": "system",
              "content": REVIEW_PROMPT.format(
                  task=task[:300],
                  actions=actions_text,
                  conclusion=conclusion[:500])},
             {"role": "user", "content": "请审查"}],
            max_tokens=500, temperature=0.3,
            thinking="disabled", timeout=15.0)
        m = re.search(r'\{[\s\S]*?\}', out or "")
        if m:
            d = json.loads(m.group())
            issues = d.get("issues", [])
            overall = d.get("overall", "PASS")
            high_count = sum(1 for i in issues if i.get("severity") == "high")
            return {
                "layer": 2, "type": "adversarial",
                "pass": overall == "PASS" and high_count == 0,
                "issues": issues,
                "overall": overall,
                "high_count": high_count,
                "detail": f"{len(issues)} 个问题"
                          + (f"（{high_count} 个高危）" if high_count else ""),
            }
    except Exception:
        pass
    return None
