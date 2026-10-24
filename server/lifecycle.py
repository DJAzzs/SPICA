"""进程注册表与优雅关停。

- SPICA 派生的每个子进程（dsh sdk/headless、TTS worker 等）都以
  start_new_session=True 启动（自成进程组），注册到 run/procs.json。
- killall：按注册表 SIGTERM 各 pgid → 等 5s → SIGKILL 兜底；幂等。
- CLI：python -m server.lifecycle --killall / --list
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from server.config import PROCS_FILE, RUN_DIR

_TERM_WAIT_S = 5.0


def _load() -> dict:
    if PROCS_FILE.exists():
        try:
            return json.loads(PROCS_FILE.read_text("utf-8"))
        except Exception:
            return {"procs": []}
    return {"procs": []}


def _save(data: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PROCS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def register(tag: str, pid: int, args: list[str] | None = None) -> None:
    """注册外部启动的子进程（如 asyncio 子进程）。"""
    data = _load()
    data["procs"].append(
        {
            "tag": tag,
            "pid": pid,
            "pgid": pid,  # 约定：SPICA 派生子进程均 start_new_session
            "args": args or [],
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )
    _save(data)


def spawn(tag: str, args: list[str], **kw) -> subprocess.Popen:
    """注册式派生子进程：自成进程组，写入注册表。"""
    proc = subprocess.Popen(
        args,
        start_new_session=True,
        **kw,
    )
    data = _load()
    data["procs"].append(
        {
            "tag": tag,
            "pid": proc.pid,
            "pgid": proc.pid,  # start_new_session ⇒ pgid == pid
            "args": args,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )
    _save(data)
    return proc


def reap() -> list[dict]:
    """清掉已退出的注册项，返回存活项。"""
    data = _load()
    alive = [p for p in data["procs"] if _alive(p["pid"])]
    data["procs"] = alive
    _save(data)
    return alive


def killall(verbose: bool = True) -> int:
    """TERM→等待→KILL 全部注册进程（不含自身进程组）。返回处理数量。"""
    my_pgid = os.getpgid(0)
    targets = reap()
    n = 0
    for p in targets:
        try:
            if p["pgid"] == my_pgid:
                continue
            os.killpg(p["pgid"], signal.SIGTERM)
            n += 1
        except OSError:
            pass
    deadline = time.time() + _TERM_WAIT_S
    while time.time() < deadline:
        if not any(_alive(p["pid"]) for p in targets):
            break
        time.sleep(0.2)
    for p in targets:
        try:
            if _alive(p["pid"]) and p["pgid"] != my_pgid:
                os.killpg(p["pgid"], signal.SIGKILL)
        except OSError:
            pass
    data = _load()
    data["procs"] = []
    _save(data)
    if verbose:
        print(f"[lifecycle] 已清扫 {n} 个进程组，注册表清空。")
    return n


def main() -> int:
    if "--killall" in sys.argv:
        killall()
        return 0
    alive = reap()
    for p in alive:
        print(f'{p["tag"]:12} pid={p["pid"]:7} {p["args"][:3]}')
    print(f"[lifecycle] 存活 {len(alive)} 项。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
