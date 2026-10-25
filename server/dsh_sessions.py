"""DSH 原生会话扫描：从 ~/.dsh/sessions/ 发现并导入 DSH 创建的会话。

- 目录名编码工作区路径（~XXXX 为 Unicode 码点，- 为路径分隔）
- 每个会话目录含 session.v4.jsonl.zstd（zstd 压缩的 JSONL）
- 首行含元数据（id/cwd/createdAt），后续行含 title/user message
- 用 zstdcat 子进程解压（无需 Python zstandard 库）
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

DSH_SESSIONS = Path.home() / ".dsh" / "sessions"
MAX_SCAN = 60          # 最多扫描数
CACHE_TTL = 30          # 缓存秒数
_cache: dict = {"at": 0, "items": []}


def _decode_dirname(name: str) -> str:
    """--home-dja-~684C~9762-SPICA-- → /home/dja/桌面/SPICA"""
    import re
    s = name.strip("-")
    # ~XXXX → Unicode char
    s = re.sub(r"~([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)
    # 剩余 - → /
    return "/" + s.replace("-", "/") if s else ""


def _read_head(zstd_path: Path, max_lines: int = 50) -> list[dict]:
    """zstdcat 解压前 N 行 JSON。"""
    try:
        out = subprocess.run(
            ["zstdcat", "-q", str(zstd_path)],
            capture_output=True, text=True, timeout=5,
        )
        lines = []
        for line in out.stdout.splitlines()[:max_lines]:
            try:
                lines.append(json.loads(line))
            except Exception:
                continue
        return lines
    except Exception:
        return []


def scan_dsh_sessions(force: bool = False) -> list[dict]:
    """扫描 DSH 会话，返回 SPICA 兼容的元数据列表。"""
    now = time.time()
    if not force and _cache["items"] and now - _cache["at"] < CACHE_TTL:
        return _cache["items"]

    items: list[dict] = []
    if not DSH_SESSIONS.exists():
        _cache.update({"at": now, "items": items})
        return items

    # 遍历工作区目录
    for ws_dir in sorted(DSH_SESSIONS.iterdir()):
        if not ws_dir.is_dir():
            continue
        cwd = _decode_dirname(ws_dir.name)
        # 遍历该工作区下的会话
        for sess_dir in ws_dir.iterdir():
            if not sess_dir.is_dir():
                continue
            zstd = sess_dir / "session.v4.jsonl.zstd"
            if not zstd.exists():
                continue
            sid = sess_dir.name  # session-xxx 或 spica-xxx
            mtime = zstd.stat().st_mtime

            # 读前 50 行提取元数据
            lines = _read_head(zstd)
            meta = lines[0] if lines and lines[0].get("type") == "session" else {}
            title = ""
            first_msg = ""
            for e in lines:
                if e.get("type") == "session/title":
                    title = (e.get("data") or {}).get("title", "")
                if e.get("type") == "user/message":
                    content = (e.get("data") or {}).get("content", [])
                    for b in (content if isinstance(content, list) else []):
                        if b.get("type") == "text":
                            first_msg = b["text"][:60]
                            break
                    if first_msg:
                        break

            items.append({
                "id": sid,
                "dsh_session_id": sid,
                "title": title or first_msg or sid[:20],
                "created": meta.get("createdAt", 0) / 1000 or mtime,
                "updated": mtime,
                "cwd": meta.get("cwd", cwd),
                "perm": "workspace-write",
                "model": "",
                "source": "dsh",      # 标记来源
            })
            if len(items) >= MAX_SCAN:
                break
        if len(items) >= MAX_SCAN:
            break

    items.sort(key=lambda x: -x.get("updated", 0))
    _cache.update({"at": now, "items": items})
    return items
