"""复杂度评分 — 决定缜密模式下是否值得升到 L3。"""

from __future__ import annotations

import re


def complexity_score(task_text: str, ctx: dict) -> int:
    """任务复杂度评分（0-10）。≥6 建议升 L3。"""
    score = 0
    text = task_text.lower()

    # 破坏性操作
    if re.search(r"删除|覆盖|overwrite|rm |drop|truncate|清空|重置", text):
        score += 3
    # 部署/上线
    if re.search(r"部署|deploy|production|上线|发布|release|publish", text):
        score += 3
    # 多文件修改
    modified = ctx.get("modified_files", [])
    if len(modified) > 5:
        score += 2
    elif len(modified) > 2:
        score += 1
    # 上次验证失败
    if ctx.get("previous_verify_failed"):
        score += 2
    # 定制模式（改自身代码）
    if ctx.get("mode") == "custom":
        score += 2
    # 长任务
    if ctx.get("turn_duration", 0) > 120:  # 超过2分钟
        score += 1
    # 涉及数据库/配置
    if re.search(r"数据库|database|config|配置|migration|迁移", text):
        score += 1

    return min(score, 10)


def should_escalate_l3(task_text: str, ctx: dict) -> bool:
    """是否值得花 L3 的钱（多版本并行验证）。"""
    return complexity_score(task_text, ctx) >= 6
