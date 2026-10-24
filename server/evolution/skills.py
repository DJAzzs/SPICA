"""自进化 · 技能库（程序性记忆，全自动收获）。

- 技能存于 会话工作区 skills/<name>/SKILL.md（Agent 的 read/bash 可直接读）
- 渐进披露：任务 prompt 只注入索引（名称+触发条件+路径），全文按需自取
- SKILL.md 结构：frontmatter(name/description/when_to_use) + 正文
  （Procedure / Pitfalls / Verification）
- 自动收获：复杂任务成功后由 LLM 从过程提炼，写库 + 审计 + 通知（可撤销）
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from server.evolution.memory import audit

SKILL_TEMPLATE = """---
name: {name}
description: {desc}
when_to_use: {when}
source: {source}
created: {ts}
---
# {name}

## When to Use
{when}

## Procedure
{steps}

## Pitfalls
{pitfalls}

## Verification
{verify}
"""

FM_PAT = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n", re.S)


class SkillStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 读取
    def _dirs(self) -> list[Path]:
        return sorted([d for d in self.root.iterdir()
                       if d.is_dir() and (d / "SKILL.md").exists()])

    def meta(self, d: Path) -> dict:
        text = (d / "SKILL.md").read_text("utf-8")
        m = FM_PAT.match(text)
        fm: dict[str, str] = {}
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip()
        return {"name": fm.get("name", d.name),
                "desc": fm.get("description", ""),
                "when": fm.get("when_to_use", ""),
                "path": str(d / "SKILL.md")}

    def list(self) -> list[dict]:
        return [self.meta(d) for d in self._dirs()]

    def render_index(self, limit_bytes: int = 1400) -> str:
        """L0 索引（注入任务 prompt，全文由 Agent 按需 read）。"""
        items = self.list()
        if not items:
            return ""
        lines = ["〔可用技能（命中场景时用 read 工具读取对应 SKILL.md 获取完整步骤）〕"]
        for s in items:
            line = f"- {s['name']}：{s['when'] or s['desc']}  → {s['path']}"
            lines.append(line)
        out = "\n".join(lines)
        return out if len(out.encode()) <= limit_bytes else \
            "\n".join(lines[:6]) + "\n- …（更多技能略）"

    # ------------------------------------------------------------ 写入
    def exists(self, name: str) -> bool:
        slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name).strip("-").lower()
        return (self.root / slug / "SKILL.md").exists()

    def create(self, name: str, desc: str, when: str, steps: str,
               pitfalls: str = "无", verify: str = "按步骤核验输出",
               source: str = "auto") -> Path | None:
        name = (name or "").strip()[:40]
        if not name:
            return None
        slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name).strip("-").lower()
        if not slug:
            return None
        d = self.root / slug
        d.mkdir(parents=True, exist_ok=True)
        p = d / "SKILL.md"
        p.write_text(SKILL_TEMPLATE.format(
            name=name, desc=desc[:120], when=when[:160], steps=steps,
            pitfalls=pitfalls, verify=verify, source=source,
            ts=time.strftime("%Y-%m-%d %H:%M")), "utf-8")
        audit("skill", f"create[{source}]", f"{name}: {desc[:80]}")
        return p

    def upsert(self, name: str, **kw) -> Path | None:
        """已有则跳过（幂等），新则创建。"""
        if self.exists(name):
            audit("skill", "skip-dup", name)
            return None
        return self.create(name, **kw)

    def delete(self, name: str) -> bool:
        for d in self._dirs():
            if self.meta(d)["name"] == name or d.name == name:
                shutil.rmtree(d, ignore_errors=True)
                audit("skill", "delete", name)
                return True
        return False
