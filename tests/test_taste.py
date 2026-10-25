"""音乐偏好学习测试。"""
import json

import pytest

from server.media.taste import MusicTaste


@pytest.fixture
def taste(tmp_path):
    return MusicTaste(tmp_path / "taste.json")


def test_record_and_persist(taste, tmp_path):
    taste.record("英文摇滚", "Bohemian Rhapsody", "Queen")
    taste.record("英文摇滚", "It's My Life", "Bon Jovi")
    taste.record("钢琴曲", "River Flows in You", "Yiruma")
    # 重新加载验证持久化
    t2 = MusicTaste(tmp_path / "taste.json")
    assert t2.data["keywords"]["英文摇滚"] == 2
    assert t2.data["total"] == 3
    assert t2.data["artists"]["Queen"] == 1
    assert len(t2.data["recent"]) == 3


def test_suggest_explore_when_empty(taste):
    kw, explored = taste.suggest()
    assert explored is True          # 冷启动：探索池
    assert kw                        # 非空关键词


def test_suggest_weighted_by_taste(taste, monkeypatch):
    for i in range(20):
        taste.record("钢琴曲", f"p{i}", "a")
    for i in range(3):
        taste.record("摇滚", f"r{i}", "b")
    # 喜好主导（禁探索时）
    counts = {"钢琴曲": 0, "摇滚": 0}
    for _ in range(200):
        kw, _ = taste.suggest(explore_ratio=0.0)
        counts[kw] += 1
    assert counts["钢琴曲"] > counts["摇滚"] * 2   # 高频权重显著更大
    assert counts["摇滚"] > 0                      # 长尾仍有机会（count^0.7）


def test_suggest_explore_ratio(taste):
    for i in range(10):
        taste.record("爵士", f"j{i}", "x")
    explored = sum(1 for _ in range(200) if taste.suggest()[1])
    assert 20 < explored < 120                      # ~30% 探索


def test_summary(taste):
    taste.record("city pop", "Plastic Love", "竹内まりや")
    s = taste.summary()
    assert "city pop" in s and "竹内まりや" in s
