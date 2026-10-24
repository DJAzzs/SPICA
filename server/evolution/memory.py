"""自进化 · 记忆系统（Hermes 式有界双文件，全自动）。

- MEMORY.md：Agent 笔记（环境事实/约定/教训），2200 字符
- USER.md：用户画像（偏好/风格），1375 字符
- 条目 § 分隔；会话开始注入冻结快照（带用量标头）
- 写入安全扫描（注入/凭据/不可见字符）；重复防护；写满强制先整合
- 全部操作记入审计日志（run/evolution-audit.jsonl）
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path

from server.config import ROOT

MEM_DIR = ROOT / "run" / "memory"
AUDIT = ROOT / "run" / "evolution-audit.jsonl"

LIMITS = {"memory": 2200, "user": 1375}
TITLES = {"memory": "MEMORY (agent notes)", "user": "USER PROFILE"}

# 安全扫描模式：prompt 注入 / 凭据外泄 / 后门
_INJECT_PAT = re.compile(
    r"ignore (all )?(previous|prior) instructions|disregard .{0,12}instructions"
    r"|you are now|system prompt|无视.{0,6}(之前|上面)的?(指令|指示)",
    re.I)
_SECRET_PAT = re.compile(
    r"sk-[A-Za-z0-9]{16,}|api[_-]?key\s*[:=]\s*\S{8,}|password\s*[:=]\s*\S{6,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I)
_INVISIBLE = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u202a\u202b\u202c\u202d\u202e\ufeff"), None)


def audit(kind: str, action: str, detail: str = "") -> None:
    try:
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind,
                                "action": action, "detail": detail[:300]},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def _safe(text: str) -> str | None:
    """返回拒因（None=安全）。记忆会进 system prompt，是攻击面。"""
    clean = text.translate(_INVISIBLE)
    if clean != text:
        return "包含不可见 Unicode 字符"
    if _INJECT_PAT.search(text):
        return "疑似提示注入内容"
    if _SECRET_PAT.search(text):
        return "疑似包含凭据/密钥"
    return None


class MemoryStore:
    def __init__(self, root: Path | None = None):
        self.root = root or MEM_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _file(self, kind: str) -> Path:
        return self.root / ("MEMORY.md" if kind == "memory" else "USER.md")

    # ------------------------------------------------------------ 读取
    def entries(self, kind: str) -> list[str]:
        f = self._file(kind)
        if not f.exists():
            return []
        raw = f.read_text("utf-8").strip()
        return [e.strip() for e in raw.split("§") if e.strip()]

    def usage(self, kind: str) -> tuple[int, int]:
        n = sum(len(e) for e in self.entries(kind))
        return n, LIMITS[kind]

    def render(self, kind: str) -> str:
        """冻结快照（注入 prompt 用）。"""
        es = self.entries(kind)
        used, limit = self.usage(kind)
        if not es:
            return ""
        head = (f"══ {TITLES[kind]} "
                f"[{used * 100 // limit}% — {used}/{limit} chars] ══")
        return head + "\n" + "§".join(es)

    # ------------------------------------------------------------ 写入
    def add(self, kind: str, text: str, source: str = "manual") -> tuple[bool, str]:
        text = (text or "").strip()
        if not text:
            return False, "空条目"
        reason = _safe(text)
        if reason:
            audit("memory", "reject", f"{reason}: {text[:60]}")
            return False, f"安全扫描未通过：{reason}"
        es = self.entries(kind)
        if any(text == e for e in es):
            return True, "重复项，未添加"
        used, limit = self.usage(kind)
        if used + len(text) + 1 > limit:
            return False, (f"记忆已满（{used}/{limit}），请先整合或删除旧条目。"
                           f"当前条目：{es}")
        es.append(text)
        self._write(kind, es)
        audit("memory", f"add[{source}]", text)
        return True, "已记住"

    def replace(self, kind: str, old_sub: str, new_text: str,
                source: str = "manual") -> tuple[bool, str]:
        es = self.entries(kind)
        hits = [i for i, e in enumerate(es) if old_sub in e]
        if not hits:
            return False, f"未找到包含 “{old_sub}” 的条目"
        if len(hits) > 1:
            return False, f"“{old_sub}” 匹配到 {len(hits)} 条，请提供更具体的片段"
        reason = _safe(new_text)
        if reason:
            return False, f"安全扫描未通过：{reason}"
        old = es[hits[0]]
        es[hits[0]] = new_text.strip()
        self._write(kind, es)
        audit("memory", f"replace[{source}]", f"{old[:50]} → {new_text[:50]}")
        return True, "已更新"

    def remove(self, kind: str, old_sub: str,
               source: str = "manual") -> tuple[bool, str]:
        es = self.entries(kind)
        hits = [i for i, e in enumerate(es) if old_sub in e]
        if not hits:
            return False, f"未找到包含 “{old_sub}” 的条目"
        if len(hits) > 1:
            return False, f"“{old_sub}” 匹配到 {len(hits)} 条，请提供更具体的片段"
        old = es.pop(hits[0])
        self._write(kind, es)
        audit("memory", f"remove[{source}]", old)
        return True, f"已删除：{old[:40]}"

    def _write(self, kind: str, es: list[str]) -> None:
        self._file(kind).write_text("§".join(es), "utf-8")
