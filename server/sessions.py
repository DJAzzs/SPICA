"""本地会话存储：索引 + 逐会话事件流。

- run/sessions.json   会话元数据列表
- run/sessions/<id>.jsonl   每会话消息事件流（追加）
元数据：{id, title, created, updated, dsh_session_id, cwd, perm, model}
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from server.config import ROOT, WORKSPACE_DIR

STORE_DIR = ROOT / "run" / "sessions"
INDEX = ROOT / "run" / "sessions.json"

PERMS = ("read-only", "workspace-write", "danger-full-access")


class SessionStore:
    def __init__(self):
        STORE_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 索引
    def _load(self) -> list[dict]:
        if INDEX.exists():
            try:
                return json.loads(INDEX.read_text("utf-8"))
            except Exception:
                return []
        return []

    def _save(self, items: list[dict]) -> None:
        INDEX.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                         "utf-8")

    def list(self) -> list[dict]:
        return sorted(self._load(), key=lambda m: m.get("updated", 0),
                      reverse=True)

    def get(self, sid: str) -> dict | None:
        return next((m for m in self._load() if m["id"] == sid), None)

    def upsert(self, meta: dict) -> dict:
        meta["updated"] = time.time()
        items = self._load()
        for i, m in enumerate(items):
            if m["id"] == meta["id"]:
                items[i] = meta
                break
        else:
            items.append(meta)
        self._save(items)
        return meta

    def delete(self, sid: str) -> None:
        self._save([m for m in self._load() if m["id"] != sid])
        f = STORE_DIR / f"{sid}.jsonl"
        f.unlink(missing_ok=True)

    def create(self, cwd: str | None = None,
               perm: str = "workspace-write") -> dict:
        meta = {
            "id": uuid.uuid4().hex[:12],
            "title": "",
            "created": time.time(),
            "updated": time.time(),
            "dsh_session_id": "",
            "cwd": cwd or str(WORKSPACE_DIR),
            "perm": perm if perm in PERMS else "workspace-write",
            "model": "",
        }
        self.upsert(meta)
        return meta

    def update(self, sid: str, patch: dict) -> dict | None:
        meta = self.get(sid)
        if not meta:
            return None
        # 允许空串清空的字段（如 model_override="" 切回自动路由）
        nullable = {"model_override", "reasoning_effort_override", "title",
                    "mode", "thorough", "multi_agent", "ma_preset"}
        for k in ("title", "cwd", "perm", "model", "model_override",
                  "reasoning_effort_override", "mode", "thorough",
                  "multi_agent", "ma_preset", "dsh_session_id"):
            if k in patch and (patch[k] is not None or k in nullable):
                meta[k] = patch[k]
        return self.upsert(meta)

    # ------------------------------------------------------------ 事件流
    def append_event(self, sid: str, role: str, text: str) -> None:
        f = STORE_DIR / f"{sid}.jsonl"
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"role": role, "text": text,
                                 "ts": time.time()}, ensure_ascii=False) + "\n")
        meta = self.get(sid)
        if meta:
            self.upsert(meta)  # 刷新 updated

    def events(self, sid: str) -> list[dict]:
        f = STORE_DIR / f"{sid}.jsonl"
        if not f.exists():
            return []
        out = []
        for line in f.read_text("utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
