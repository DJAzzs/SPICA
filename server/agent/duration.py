"""任务耗时预测器 — 基于历史任务统计，为新任务预估时间。

数据：run/task-durations.json
  { categories: { "code": {count, total_s, avg_s, min_s, max_s}, ... },
    recent: [{text, category, seconds, ts}] }

分类规则（关键词匹配，无需 LLM）：
  code     写/创建/修改/删除 文件/代码/脚本/函数/组件
  search   搜索/查找/分析/调查/浏览/研究
  install  安装/部署/配置/初始化/搭建
  quick    简单问答（一句话能答的）
  general  其他
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

DATA_FILE = Path("run") / "task-durations.json"
MAX_RECENT = 50

CATEGORIES = {
    "code": re.compile(
        r"写|创建|修改|编辑|删除|重构|添加|实现|fix|bug|debug|"
        r"代码|脚本|函数|组件|文件|模块|api|接口|ui|样式", re.I),
    "search": re.compile(
        r"搜索|查找|找|分析|调查|研究|浏览|查看|检查|测试|"
        r"对比|评估|review|explore|investigate", re.I),
    "install": re.compile(
        r"安装|部署|配置|初始化|搭建|设置|环境|install|setup|deploy|init", re.I),
    "quick": re.compile(
        r"什么|怎么|为什么|是否|多少|几|哪|who|what|how|why|is|are|can", re.I),
}


def _categorize(text: str) -> str:
    """按优先级匹配任务类别。"""
    for cat, pattern in CATEGORIES.items():
        if cat == "quick":
            continue  # quick 最低优先级
        if pattern.search(text):
            return cat
    if CATEGORIES["quick"].search(text):
        return "quick"
    return "general"


def _load() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {"categories": {}, "recent": []}


def _save(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def record(text: str, seconds: float) -> None:
    """任务完成后记录实际耗时。"""
    data = _load()
    cat = _categorize(text)

    # 更新分类统计
    if cat not in data["categories"]:
        data["categories"][cat] = {"count": 0, "total_s": 0,
                                    "avg_s": 0, "min_s": 0, "max_s": 0}
    c = data["categories"][cat]
    c["count"] += 1
    c["total_s"] += seconds
    c["avg_s"] = c["total_s"] / c["count"]
    c["min_s"] = min(c["min_s"], seconds) if c["min_s"] else seconds
    c["max_s"] = max(c["max_s"], seconds)

    # 最近记录
    data["recent"].append({
        "text": text[:80], "category": cat,
        "seconds": round(seconds, 1), "ts": time.time()})
    data["recent"] = data["recent"][-MAX_RECENT:]

    _save(data)


def estimate(text: str) -> tuple[float, str] | None:
    """预估任务耗时。返回 (seconds, category) 或 None（无历史数据）。

    策略：
    1. 同类任务历史 ≥3 次 → 用中位数（比平均更抗极端值）
    2. 同类任务 1-2 次 → 用平均值
    3. 无历史 → None（不预估）
    """
    data = _load()
    cat = _categorize(text)
    c = data["categories"].get(cat)

    if not c or c["count"] < 1:
        # 尝试用最近的全局平均
        all_times = [r["seconds"] for r in data.get("recent", [])[-10:]]
        if len(all_times) >= 3:
            all_times.sort()
            mid = all_times[len(all_times) // 2]
            return (mid, cat)
        return None

    if c["count"] >= 3:
        # 用该类最近 N 次的中位数
        cat_recent = [r["seconds"] for r in data.get("recent", [])
                      if r["category"] == cat][-10:]
        if cat_recent:
            cat_recent.sort()
            return (cat_recent[len(cat_recent) // 2], cat)

    return (c["avg_s"], cat)


def format_duration(seconds: float) -> str:
    """秒 → 人类可读。"""
    if seconds < 60:
        return f"~{seconds:.0f} 秒"
    if seconds < 3600:
        return f"~{seconds / 60:.0f} 分钟"
    return f"~{seconds / 3600:.1f} 小时"


def get_estimate_text(text: str) -> str | None:
    """获取预估文本（直接可播报）。"""
    result = estimate(text)
    if not result:
        return None
    seconds, cat = result
    return format_duration(seconds)
