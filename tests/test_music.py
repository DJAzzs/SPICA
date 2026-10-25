"""音乐集成测试（mock MusicFree，不发真实请求）。"""
import asyncio
import json

import pytest


class FakeMusic:
    @staticmethod
    async def ping():
        return True, "MusicFree 1.2.5"

    @staticmethod
    async def pick(keyword):
        if keyword == "不存在的东西xyz":
            return None
        return {"id": "s1", "title": "晴天", "artist": "周杰伦",
                "duration": 269, "cover": "cov1"}


@pytest.fixture
def sem_music(tmp_path, monkeypatch):
    import server.sessions as S
    monkeypatch.setattr(S, "STORE_DIR", tmp_path / "s")
    monkeypatch.setattr(S, "INDEX", tmp_path / "s.json")
    import server.evolution.memory as EM
    monkeypatch.setattr(EM, "MEM_DIR", tmp_path / "m")
    monkeypatch.setattr(EM, "AUDIT", tmp_path / "a.jsonl")
    from server.agent.semantics import Semantics
    from tests.test_semantics import (FakePipeline, FakeSdk, FakeNarrator,
                                      FakePacks, FakeRewriter, FakeRouter)
    from server.config import load_settings
    from server.evolution.skills import SkillStore
    monkeypatch.setattr("server.media.musicfree.MusicFree", FakeMusic)
    events = []

    async def bc(e):
        events.append(e)
    sem = Semantics(FakePipeline(), FakeSdk(), FakeRewriter(), FakeRouter(),
                    FakeNarrator(), FakePacks(), None, bc, load_settings(),
                    store=S.SessionStore(),
                    memory_store=EM.MemoryStore(tmp_path / "m"),
                    skill_store=SkillStore(tmp_path / "sk"))
    monkeypatch.setattr(sem, "_archive", lambda: tmp_path / "arch")
    monkeypatch.setattr(sem, "self_stop", lambda: None)
    return sem, events


def run(coro):
    return asyncio.run(coro)


def test_music_play_broadcasts_track(sem_music):
    sem, events = sem_music
    run(sem.music_play("周杰伦 晴天"))
    tr = next(e for e in events if e.get("t") == "music_track")
    assert tr["title"] == "晴天" and tr["id"] == "s1"
    # 少即是多：不再发"开始播放"文字（音乐卡即反馈）


def test_music_play_no_result(sem_music):
    sem, events = sem_music
    run(sem.music_play("不存在的东西xyz"))
    assert any("没有找到" in e.get("text", "") for e in events)


def test_music_stop(sem_music):
    sem, events = sem_music
    run(sem.music_stop(quiet=True))
    assert any(e.get("t") == "music_stop" for e in events)


def test_slash_music_routes(sem_music):
    sem, events = sem_music
    run(sem.slash("music", "stop"))
    assert any(e.get("t") == "music_stop" for e in events)
    run(sem.slash("music", "播放 夜曲"))
    assert any(e.get("t") == "music_track" for e in events)


def test_voice_music_play_and_stop(sem_music):
    sem, events = sem_music
    assert run(sem._try_voice_command("放一首周杰伦的晴天"))
    assert any(e.get("t") == "music_track" for e in events)
    assert run(sem._try_voice_command("把音乐停了"))
    assert any(e.get("t") == "music_stop" for e in events)


def test_auto_pick_disabled_by_default(sem_music):
    sem, events = sem_music
    run(sem.music_auto_pick("写代码"))
    assert not any(e.get("t") == "music_track" for e in events)  # 默认关
