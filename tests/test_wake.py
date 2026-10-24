"""唤醒词/结束词/语义指令匹配器单测。"""
import pytest

from server.voice.wake import Matcher, normalize, pinyin_key, word_keys, command_entries
from server.config import DEFAULT_WAKE_WORDS, DEFAULT_FAREWELL_WORDS, DEFAULT_COMMANDS


@pytest.fixture
def m() -> Matcher:
    return Matcher()  # 使用生产默认阈值（88）


# ---------------------------------------------------------------- 归一化
def test_normalize():
    assert normalize("Hey, SPICA!") == "heyspica"
    assert normalize("嘿 SPICA，在吗？") == "嘿spica在吗"
    assert normalize("  Bye   Spica ") == "byespica"


def test_pinyin_key():
    assert pinyin_key("黑spica") == pinyin_key("嘿spica")  # 同音异字
    assert pinyin_key("拜拜斯必卡") == "baibaisibika"


# ---------------------------------------------------------------- 唤醒词
def test_wake_exact_english(m):
    hit = m.match_prefix("Hey, SPICA 帮我写个脚本", DEFAULT_WAKE_WORDS, "wake")
    assert hit is not None and hit.kind == "wake"
    assert "脚本" in hit.remainder or hit.remainder  # 有剩余指令


def test_wake_exact_chinese(m):
    hit = m.match_prefix("嘿SPICA，今天天气怎么样", DEFAULT_WAKE_WORDS, "wake")
    assert hit is not None and hit.kind == "wake"
    assert "天气" in hit.remainder


def test_wake_variant_chinese(m):
    """ASR 把 SPICA 听成中文谐音。"""
    hit = m.match_prefix("嘿思必卡帮我打开网页", DEFAULT_WAKE_WORDS, "wake")
    assert hit is not None and hit.kind == "wake"


def test_wake_variant_english(m):
    """ASR 把 spica 听成 speaker。"""
    hit = m.match_prefix("hey speaker 帮我查一下", DEFAULT_WAKE_WORDS, "wake")
    assert hit is not None and hit.kind == "wake"


def test_wake_homophone(m):
    """同音异字靠拼音键命中。"""
    hit = m.match_prefix("黑spica在吗", DEFAULT_WAKE_WORDS, "wake")
    assert hit is not None


def test_no_wake_on_ordinary(m):
    assert m.match_prefix("帮我写一个 python 脚本", DEFAULT_WAKE_WORDS, "wake") is None
    assert m.match_prefix("今天聊聊 spaghetti 的做法", DEFAULT_WAKE_WORDS, "wake") is None


def test_disabled_word(m):
    words = [dict(DEFAULT_WAKE_WORDS[0], enabled=False)]
    assert m.match_prefix("Hey, SPICA", words, "wake") is None


# ---------------------------------------------------------------- 结束词
def test_farewell_anywhere(m):
    hit = m.match_anywhere("好了今天就到这里，Bye, SPICA", DEFAULT_FAREWELL_WORDS, "farewell")
    assert hit is not None and hit.kind == "farewell"


def test_farewell_chinese_variant(m):
    hit = m.match_anywhere("拜拜斯必卡", DEFAULT_FAREWELL_WORDS, "farewell")
    assert hit is not None


def test_wake_not_confused_with_farewell(m):
    assert m.match_anywhere("Hey, SPICA 帮个忙", DEFAULT_FAREWELL_WORDS, "farewell") is None


# ---------------------------------------------------------------- 语义指令
def test_command_pause(m):
    entries = command_entries(DEFAULT_COMMANDS)
    assert m.match_anywhere("暂停一下", entries["pause"], "command:pause") is not None
    assert m.match_anywhere("先停一下", entries["pause"], "command:pause") is not None


def test_command_resume(m):
    entries = command_entries(DEFAULT_COMMANDS)
    assert m.match_anywhere("继续执行", entries["resume"], "command:resume") is not None


def test_word_keys_dedup():
    keys = word_keys({"phrase": "Hey, SPICA", "variants": ["hey spica", "heyspica"]})
    assert len(keys) == len(set(keys))
    assert "heyspica" in keys
