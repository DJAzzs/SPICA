"""验证报告生成 — 结构化 JSON → 前端事件格式。"""

from __future__ import annotations

from datetime import datetime


def generate_report(checks: list[dict], elapsed_ms: int,
                    retries: int = 0) -> dict:
    """汇总各层检查结果 → 验证报告。

    overall:
      PASS — 全部通过
      PASS_WITH_WARNINGS — 有 low/medium 问题但不影响交付
      FAIL — 有 high 问题，触发修正
    """
    all_pass = all(c.get("pass", True) for c in checks)
    has_high = any(
        c.get("high_count", 0) > 0 or
        any(i.get("severity") == "high" for i in c.get("issues", []))
        for c in checks)
    has_medium = any(
        any(i.get("severity") == "medium" for i in c.get("issues", []))
        for c in checks)
    has_contradiction = any(
        c.get("contradictions") for c in checks)

    if all_pass and not has_high and not has_contradiction:
        overall = "PASS"
    elif has_high or has_contradiction:
        overall = "FAIL"
    else:
        overall = "PASS_WITH_WARNINGS"

    layers = sorted(set(c.get("layer", 0) for c in checks))

    return {
        "t": "verify_report",
        "overall": overall,
        "checks": checks,
        "layers_used": layers,
        "retries": retries,
        "elapsed_ms": elapsed_ms,
        "timestamp": datetime.now().isoformat(),
    }
