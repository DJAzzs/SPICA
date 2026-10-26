"""验证引擎编排器 — turn_done 后按模式/开关选级 → 逐层执行 → 汇总报告。"""

from __future__ import annotations

import time

from server.verify.post_conditions import run_l0
from server.verify.consistency import run_l1
from server.verify.adversarial import run_l2
from server.verify.cross_validate import run_l3
from server.verify.complexity import should_escalate_l3
from server.verify.report import generate_report


async def run_verification(sem, task_text: str, summary: str,
                           turn_context: dict) -> dict | None:
    """执行验证管线。

    Args:
        sem: Semantics 实例（取 mode/thorough/llm/session 等）
        task_text: 原始任务文本
        summary: Agent 最终总结
        turn_context: {
            created_files: list[str],
            modified_files: list[str],
            tool_outputs: list[str],
            actions: list[str],  # 操作摘要
        }

    Returns:
        验证报告 dict（可直接 broadcast），或 None（跳过验证）
    """
    t0 = time.time()
    mode = sem._get_mode()
    thorough = sem._is_thorough()

    # 极简模式：跳过全部验证
    if mode == "minimal":
        return None

    # 常规模式（thorough 关）：只跑 L0
    checks = run_l0({
        **turn_context,
        "cwd": sem.session.get("cwd", ""),
        "test_cmd": _detect_test_cmd(sem.session.get("cwd", "")),
    })

    # 缜密模式：L1 + L2 + 按需 L3
    if thorough:
        # L1: 语义一致性
        l1 = await run_l1(
            agent_summary=summary,
            tool_outputs=turn_context.get("tool_outputs", []),
            llm=sem.llm)
        if l1:
            checks.append(l1)

        # L2: 对抗审查
        l2 = await run_l2(
            task=task_text,
            actions=turn_context.get("actions", []),
            conclusion=summary,
            llm=sem.llm)
        if l2:
            checks.append(l2)

        # L3: 交叉验证（仅复杂度触发）
        ctx_for_complexity = {
            **turn_context,
            "mode": mode,
            "previous_verify_failed": getattr(sem, "_last_verify_failed", False),
        }
        if should_escalate_l3(task_text, ctx_for_complexity):
            l3 = await run_l3(
                task=task_text,
                primary_result=summary,
                llm=sem.llm)
            if l3:
                checks.append(l3)

    elapsed = int((time.time() - t0) * 1000)
    report = generate_report(checks, elapsed)

    # 记录失败状态（下次复杂度评分用）
    sem._last_verify_failed = report["overall"] == "FAIL"

    return report


def _detect_test_cmd(cwd: str) -> str | None:
    """检测项目的测试命令。"""
    from pathlib import Path
    root = Path(cwd)
    if not root.exists():
        return None
    if (root / "package.json").exists():
        return "npm test -- --silent 2>/dev/null || true"
    if (root / "Makefile").exists():
        return "make test"
    if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
        return "pytest --tb=no -q"
    return None
