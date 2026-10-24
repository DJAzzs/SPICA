"""会话存储与管理单测。"""
import json

import pytest

from server.sessions import SessionStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    import server.sessions as S
    monkeypatch.setattr(S, "STORE_DIR", tmp_path / "sessions")
    monkeypatch.setattr(S, "INDEX", tmp_path / "sessions.json")
    s = SessionStore()
    s.STORE_DIR = S.STORE_DIR
    return s


def test_create_upsert_list(store):
    a = store.create()
    b = store.create(cwd="/tmp/x")
    assert b["cwd"] == "/tmp/x"
    assert [m["id"] for m in store.list()][:2] == [b["id"], a["id"]]  # 新的在前


def test_update_and_perm_validation(store):
    m = store.create()
    up = store.update(m["id"], {"title": "图片分析", "perm": "read-only"})
    assert up["title"] == "图片分析" and up["perm"] == "read-only"
    assert store.update("不存在", {"title": "x"}) is None


def test_events_append_and_read(store):
    m = store.create()
    store.append_event(m["id"], "user", "分析图片")
    store.append_event(m["id"], "assistant", "已完成")
    evs = store.events(m["id"])
    assert [e["text"] for e in evs] == ["分析图片", "已完成"]


def test_delete_removes_events(store):
    m = store.create()
    store.append_event(m["id"], "user", "hi")
    store.delete(m["id"])
    assert store.get(m["id"]) is None
    assert store.events(m["id"]) == []


def test_semantics_session_flow(tmp_path, monkeypatch):
    """新建→任务绑定 dsh id→打开历史→删除。"""
    import server.sessions as S
    monkeypatch.setattr(S, "STORE_DIR", tmp_path / "s")
    monkeypatch.setattr(S, "INDEX", tmp_path / "s.json")
    from server.agent.semantics import Semantics
    from tests.test_semantics import (FakePipeline, FakeSdk, FakeNarrator,
                                      FakePacks, FakeRewriter, FakeRouter)
    from server.config import load_settings
    import asyncio

    async def bc(e): pass
    st = S.SessionStore()
    sem = Semantics(FakePipeline(), FakeSdk(), FakeRewriter(), FakeRouter(),
                    FakeNarrator(), FakePacks(), None, bc, load_settings(),
                    store=st)
    asyncio.run(sem.session_new())
    sid = sem.session["id"]
    # 任务启动 → dsh id 回填
    sem.route_info = {"model": "glm-5.3-flash", "reasoning_effort": None}
    asyncio.run(sem._start_task("分析图片风格"))
    assert sem.session["dsh_session_id"] == "sess-test-1"
    sem._log("user", "分析图片风格")
    # 新会话 → 旧会话仍在列表
    sem.state = "idle"                      # 模拟执行结束
    asyncio.run(sem.session_new())
    ids = [m["id"] for m in st.list()]
    assert sid in ids and sem.session["id"] in ids
    # 打开旧会话：历史恢复 + resume 标记
    asyncio.run(sem.session_open(sid))
    assert sem.sdk.session_id == "sess-test-1"
    assert sem._need_resume is True
    assert any(e["text"] == "分析图片风格" for e in sem.transcript)
    # 删除
    asyncio.run(sem.session_delete(sid))
    assert st.get(sid) is None
