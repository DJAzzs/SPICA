"""唤醒词/结束词/语义指令匹配器。

设计（方案 v6 关键决策）：
- 常开流式 ASR 的 partial/final 文本上做词面模糊匹配，替代专用 KWS
  （纯拼音 KWS 拼不出 "SPICA" 这类英文生僻词）。
- 归一化两条键：纯文本键（小写、去标点空格、全角→半角）与拼音键
  （中文逐字转无声调拼音，英文保留），两条都参与匹配。
- 先精确子串命中，再 rapidfuzz partial_ratio 模糊命中（阈值可调）。
- 唤醒词约定位于句首；命中后返回剩余文本作为可能的紧随指令。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

from pypinyin import lazy_pinyin

try:  # rapidfuzz 未装时降级为仅精确匹配（单测环境保护）
    from rapidfuzz import fuzz

    _HAVE_FUZZ = True
except Exception:  # pragma: no cover
    _HAVE_FUZZ = False

_PUNCT_CHARS = " ,.!?，。！？；;：:·…\-—_‐'‘’\"“”()（）[]【】《》<>&*#@%$^~`|\\/+=~"
_PUNCT = re.compile("[" + re.escape(_PUNCT_CHARS) + "]+")


def normalize(text: str) -> str:
    """小写、全角→半角、去标点与空格。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    return _PUNCT.sub("", text)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF


def pinyin_key(text: str) -> str:
    """中文→无声调拼音，英文/数字保留。用于跨语言混淆（嘿思必卡 ≈ hey spica 不等价，
    但 拜拜斯必卡 ≈ 拜拜spica 这类中文内部变体可由文本键覆盖；拼音键主要让
    '黑spica' 与 '嘿spica' 这类同音异字命中）。"""
    norm = normalize(text)
    if not norm:
        return ""
    out: list[str] = []
    buf = ""
    for ch in norm:
        if _is_cjk(ch):
            if buf:
                out.append(buf)
                buf = ""
            out.append(lazy_pinyin(ch)[0])
        else:
            buf += ch
    if buf:
        out.append(buf)
    return "".join(out)


def word_keys(word: dict) -> list[str]:
    """一个词条的全部匹配键：phrase + variants，各自文本键与拼音键。"""
    seen: set[str] = set()
    result: list[str] = []
    for form in [word.get("phrase", "")] + list(word.get("variants") or []):
        for key in (normalize(form), pinyin_key(form)):
            if key and key not in seen:
                seen.add(key)
                result.append(key)
    return result


@dataclass
class WordHit:
    phrase: str        # 词条主词形
    kind: str          # wake | farewell | command:<name>
    score: float       # 0-100
    remainder: str     # 命中词之后的剩余归一化文本（唤醒词后紧跟指令时非空）


class Matcher:
    """对一段归一化文本做词表匹配（文本键 + 拼音键双空间）。"""

    def __init__(self, threshold: float = 88.0):
        self.threshold = threshold

    def _find(self, key: str, norm: str, pnorm: str) -> int:
        """返回 key 在文本/拼音空间的命中位置，未命中返回 -1。"""
        idx = norm.find(key)
        if idx < 0 and pnorm and pnorm != norm:
            idx = pnorm.find(key)
        return idx

    def _fuzzy(self, key: str, norm: str, pnorm: str) -> float:
        """对两个空间取 partial_ratio 最高分。"""
        if not _HAVE_FUZZ:
            return 0.0
        scores = [fuzz.partial_ratio(key, norm)]
        if pnorm and pnorm != norm:
            scores.append(fuzz.partial_ratio(key, pnorm))
        return max(scores)

    def match_prefix(self, text: str, entries: Iterable[dict], kind: str,
                     fuzzy: bool = True) -> Optional[WordHit]:
        """在归一化前缀窗口（前 40 字符）内匹配，返回命中与剩余。"""
        norm = normalize(text)
        if not norm:
            return None
        pnorm = pinyin_key(text)
        window, pwindow = norm[:40], pnorm[:48]
        best: Optional[WordHit] = None
        for entry in entries:
            if entry.get("enabled") is False:
                continue
            for key in word_keys(entry):
                hit_score: Optional[float] = None
                end = 0
                idx = self._find(key, window, pwindow)
                if idx >= 0:
                    hit_score = 100.0
                    end = idx + len(key)
                elif fuzzy and len(key) >= 6:
                    score = self._fuzzy(key, window, pwindow)
                    if score >= self.threshold:
                        hit_score = score
                if hit_score is not None:
                    remainder = norm[end:].strip() if idx >= 0 else ""
                    cand = WordHit(entry["phrase"], kind, hit_score, remainder)
                    if best is None or cand.score > best.score:
                        best = cand
                    break  # 该词条已命中
        return best

    def match_anywhere(self, text: str, entries: Iterable[dict], kind: str,
                       fuzzy: bool = True) -> Optional[WordHit]:
        """整句任意位置匹配（结束词/暂停等指令可出现在句中）。"""
        norm = normalize(text)
        if not norm:
            return None
        pnorm = pinyin_key(text)
        best: Optional[WordHit] = None
        for entry in entries:
            if entry.get("enabled") is False:
                continue
            for key in word_keys(entry):
                hit_score: Optional[float] = None
                idx = self._find(key, norm, pnorm)
                if idx >= 0:
                    hit_score = 100.0
                elif fuzzy and len(key) >= 6:
                    score = self._fuzzy(key, norm, pnorm)
                    if score >= self.threshold:
                        hit_score = score
                if hit_score is not None:
                    cand = WordHit(entry["phrase"], kind, hit_score, "")
                    if best is None or cand.score > best.score:
                        best = cand
                    break
        return best


def command_entries(commands: dict[str, list[str]]) -> dict[str, list[dict]]:
    """语义指令 {'pause': [...]} → {'pause': [{'phrase':..., 'variants':[]}]}."""
    out: dict[str, list[dict]] = {}
    for name, phrases in commands.items():
        out[name] = [
            {"phrase": p, "variants": [], "enabled": True} for p in phrases
        ]
    return out
