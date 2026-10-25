"""DSH SDK 桥客户端：spawn `dsh --profile sdk` + 薄 JSON-RPC (NDJSON stdio)。

- initialize: {cwd, provider, model, reasoningEffort?, maxTokens?}
  （reasoningEffort 即"Agent 自选推理强度"的官方接口）
- session/prompt / session/wait / session/resume / shutdown
- 通知: session.event（全量事件流）、session.status（running/idle）
- 暂停 = SIGTERM 子进程（会话已持久化）；恢复 = 重启 + resume + 注入"继续"
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from server import lifecycle
from server.config import ROOT, load_settings

DSH_BIN_CANDIDATES = [
    Path("/home/dja/.npm/_npx/b86ed90107c62dab/node_modules/.bin/dsh"),
]
PATCH = ROOT / "run" / "dsh-patch.yml"

NotificationHandler = Callable[[str, dict], Awaitable[None]]


def check_node() -> str | None:
    """返回 node 路径，不可用返回 None。"""
    import shutil
    return shutil.which("node")


def ensure_dsh_ready(settings: dict | None = None) -> tuple[bool, str]:
    """P3：检查 DSH 运行环境，返回 (ok, message)。
    优先级：用户设置 > 项目捆绑 > 系统 PATH > npx 缓存。"""
    s = settings or load_settings()

    # Node.js 必须存在
    node = check_node()
    if not node:
        return False, ("Node.js 未安装。SPICA 需要 Node.js ≥ 18 来运行 DSH 运行时。\n"
                       "安装方法：sudo apt install nodejs 或从 https://nodejs.org 下载")

    # 1. 用户显式指定
    if s.get("dsh_bin") and Path(s["dsh_bin"]).exists():
        return True, "用户配置的 DSH"

    # 2. 项目捆绑
    bundled = ROOT / "runtime" / "dsh" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    if bundled.exists():
        return True, f"捆绑 DSH 运行时（{bundled.parent.parent.parent}）"

    # 3. 系统 PATH
    import shutil
    if shutil.which("dsh"):
        return True, "系统安装的 DSH"

    # 4. npx 缓存
    for p in DSH_BIN_CANDIDATES:
        if p.exists():
            return True, f"npx 缓存的 DSH（{p}）"

    return False, ("DSH 运行时未找到。运行以下命令安装捆绑版：\n"
                   "  cd /home/dja/桌面/SPICA && make deps-dsh")


def dsh_command(settings: dict | None = None) -> list[str]:
    """DSH 可执行优先级：用户设置 > 项目捆绑 > 系统 PATH > npx 缓存。"""
    s = settings or load_settings()
    if s.get("dsh_bin"):
        return [s["dsh_bin"]]
    bundled = ROOT / "runtime" / "dsh" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    if bundled.exists():
        return ["node", str(bundled)]
    import shutil
    if shutil.which("dsh"):
        return ["dsh"]
    for p in DSH_BIN_CANDIDATES:
        if p.exists():
            return ["node", str(p)]
    raise FileNotFoundError(
        "DSH 不可达。运行 make deps-dsh 安装捆绑版，或在设置中配置 dsh_bin")


def zai_env(settings: dict | None = None) -> dict[str, str]:
    """zai 凭据注入子进程环境。"""
    from server.agent.llm import LLMClient
    env = dict(os.environ)
    key = LLMClient(settings).api_key
    if key:
        env["ZAI_CODING_CN_API_KEY"] = key
    return env


class SdkClient:
    def __init__(self, on_notification: NotificationHandler | None = None,
                 settings: dict | None = None):
        self.settings = settings or load_settings()
        self.on_notification = on_notification
        self.proc: asyncio.subprocess.Process | None = None
        self.session_id: str = ""
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ 生命周期
    async def start(self, model: str, reasoning_effort: str | None,
                    max_tokens: int | None = None,
                    cwd: str | None = None,
                    permission: str | None = None) -> str:
        """启动并 initialize。返回 session id。
        cwd：会话工作区；permission：DSH_PERMISSION_MODE
        （read-only | workspace-write | danger-full-access）。"""
        async with self._lock:
            if self.proc and self.proc.returncode is None:
                return self.session_id
            cmd = dsh_command(self.settings) + [
                "--profile", "sdk",
                "--patch", str(PATCH),
            ]
            env = zai_env(self.settings)
            if permission:
                env["DSH_PERMISSION_MODE"] = permission
            workdir = cwd or str(ROOT / "workspace")
            Path(workdir).mkdir(parents=True, exist_ok=True)
            self.proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=open(ROOT / "run" / "sdk-stderr.log", "ab"),
                cwd=workdir,
                env=env,
                start_new_session=True,
            )
            lifecycle.register("dsh-sdk", self.proc.pid, cmd)
            self._reader_task = asyncio.create_task(self._read_loop())
            params: dict = {
                "cwd": workdir,
                "provider": "zai-coding-cn",
                "model": model,
            }
            if reasoning_effort:
                params["reasoningEffort"] = reasoning_effort
            if max_tokens:
                params["maxTokens"] = max_tokens
            await self._request("initialize", params)
            if not self.session_id:
                self.session_id = f"spica-{uuid.uuid4().hex[:12]}"
            return self.session_id

    def reset_identity(self, session_id: str = "") -> None:
        """丢弃当前进程绑定，换用指定（可为空=新建）会话身份。"""
        self.pause()
        self.session_id = session_id

    async def stop(self) -> None:
        """优雅关停：shutdown 请求 + SIGTERM 兜底。"""
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self.proc and self.proc.returncode is None:
            try:
                await asyncio.wait_for(self._request("shutdown", {}), timeout=5)
            except Exception:
                pass
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except Exception:
                pass
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def pause(self) -> None:
        """硬暂停：SIGTERM（会话已持久化，resume 可续）。"""
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        self.proc = None

    # ------------------------------------------------------------ RPC
    async def _request(self, method: str, params: dict) -> Any:
        self._req_id += 1
        rid = self._req_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        line = json.dumps({"id": rid, "method": method, "params": params})
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(line.encode() + b"\n")
        await self.proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=120)

    async def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        while True:
            raw = await self.proc.stdout.readline()
            if not raw:
                break  # 进程退出
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                fut = self._pending.pop(msg["id"], None)
                if fut and not fut.done():
                    if "error" in msg:
                        fut.set_exception(
                            RuntimeError(f"RPC {msg['id']}: {msg['error']}"))
                    else:
                        fut.set_result(msg.get("result"))
            elif "method" in msg:
                method, params = msg["method"], msg.get("params", {})
                # session/created 事件拿 session id
                if method == "session/created" and not self.session_id:
                    self.session_id = params.get("sessionId", "")
                if self.on_notification:
                    try:
                        await self.on_notification(method, params)
                    except Exception:
                        pass

    # ------------------------------------------------------------ 会话
    async def prompt(self, text: str, session_id: str | None = None) -> dict:
        sid = session_id or self.session_id
        return await self._request("session/prompt", {
            "sessionId": sid,
            "contentBlocks": [{"type": "text", "text": text}],
        })

    async def wait_turn(self, session_id: str | None = None) -> None:
        await self._request("session/wait", {
            "sessionId": session_id or self.session_id})

    async def resume(self, session_id: str) -> None:
        """恢复持久化会话（重启进程后调用）。"""
        self.session_id = session_id
        await self._request("session/resume", {"sessionId": session_id})
