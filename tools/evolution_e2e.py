"""自进化 E2E：真实任务 → 自动收获技能 → 复用注入验证。
SPICA_LIVE=1 .venv/bin/python -m tools.evolution_e2e
"""
import asyncio
import json
import sys
import time
import websockets

URL = "ws://127.0.0.1:8666/ws"


async def main() -> int:
    events = []
    turn_done = asyncio.Event()

    async with websockets.connect(URL, max_size=2 ** 22) as ws:
        async def reader():
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    continue
                ev = json.loads(raw)
                events.append(ev)
                t = ev.get("t")
                if t == "turn_done":
                    turn_done.set()
                if t == "msg" and ev.get("role") == "system":
                    print(f"  [sys] {ev.get('text', '')[:90]}")

        rt = asyncio.create_task(reader())
        await asyncio.sleep(0.5)

        # 任务 1：必然 5+ 工具调用的复杂任务
        task1 = ("在 workspace 里创建 test_project 目录：写 main.py（入口）、"
                 "utils.py（两个工具函数）、README.md（用法说明），"
                 "然后统计各文件行数，把总结写进 test_project/REPORT.md")
        print("[e2e] 任务 1：复杂脚手架任务…")
        await ws.send(json.dumps({"t": "text_input", "text": task1}))
        try:
            await asyncio.wait_for(turn_done.wait(), timeout=420)
        except asyncio.TimeoutError:
            print("[e2e] 超时")
        turn_done.clear()
        await asyncio.sleep(6)   # 等异步收获完成

        # 验证技能库
        await ws.send(json.dumps({"t": "slash", "cmd": "skills", "arg": "list"}))
        await asyncio.sleep(2)
        await ws.send(json.dumps({"t": "slash", "cmd": "memory", "arg": "list"}))
        await asyncio.sleep(2)

        # 任务 2：相似任务 → prompt 应含技能索引（通过事件侧证：技能已在库）
        print("[e2e] 任务 2：相似任务（验证复用）…")
        task2 = "再帮我在 workspace 创建一个 demo_app 项目脚手架，类似的流程"
        await ws.send(json.dumps({"t": "text_input", "text": task2}))
        try:
            await asyncio.wait_for(turn_done.wait(), timeout=420)
        except asyncio.TimeoutError:
            pass
        rt.cancel()

    skills_msgs = [e.get("text", "") for e in events
                   if e.get("t") == "msg" and "技能" in e.get("text", "")]
    print("\n[e2e] 技能相关消息：")
    for s in skills_msgs:
        print("  ·", s[:100])
    import pathlib
    sk = pathlib.Path("workspace/skills")
    found = list(sk.glob("*/SKILL.md")) if sk.exists() else []
    print(f"[e2e] 技能库文件：{[str(f.parent.name) for f in found]}")
    mem = pathlib.Path("run/memory")
    for f in (mem.glob("*.md") if mem.exists() else []):
        print(f"[e2e] {f.name}: {f.read_text('utf-8')[:120]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
