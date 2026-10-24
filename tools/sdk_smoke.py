"""SDK 事件流冒烟：initialize → prompt → 收集事件 → wait → shutdown。
打印 session.event 真实形状供 bridge 精确解析。用法：
SPICA_LIVE=1 .venv/bin/python -m tools.sdk_smoke
"""
import asyncio
import json
import sys
from collections import Counter

from server.agent.sdk_client import SdkClient


async def main() -> int:
    events: list[tuple] = []
    status: list[str] = []

    async def on_note(method: str, params: dict) -> None:
        if method == "session.event":
            ev = params.get("event", {})
            events.append((params.get("sessionId"), ev))
        elif method == "session.status":
            status.append(params.get("status", ""))
        elif method.startswith("subagent"):
            events.append((method, params))

    client = SdkClient(on_notification=on_note)
    sid = await client.start(model="glm-5.3", reasoning_effort=None)
    print("session:", sid)
    await client.prompt("只回复两个字：好的", sid)
    await client.wait_turn(sid)
    await asyncio.sleep(1)
    await client.stop()

    print("status:", status)
    print(f"events: {len(events)}")
    # 事件形状摘要
    shapes = Counter()
    for _, ev in events:
        if isinstance(ev, dict):
            shapes[(ev.get("type") or ev.get("kind") or "?",
                    tuple(sorted(k for k in ev.keys() if k not in ("seq",))))] += 1
    for (typ, keys), n in shapes.most_common(20):
        print(f"  {n:3}x type={typ} keys={keys}")
    # 样本
    seen = set()
    for _, ev in events[:40]:
        typ = ev.get("type") or ev.get("kind") if isinstance(ev, dict) else "?"
        if typ not in seen:
            seen.add(typ)
            print("SAMPLE", json.dumps(ev, ensure_ascii=False)[:300])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
