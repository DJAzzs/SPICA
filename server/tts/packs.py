"""唤醒/告别应答语音包：预合成 + 缓存直读（<10ms 出声，零 LLM）。

机制：TTSEngine.synth 按 (text, voice, lang) 哈希落盘缓存——向导/
首启时 ensure_packs() 批量预生成，运行期播包 = 缓存命中读 wav，
模型无需加载。播放随机不连续重复同一条。
"""
from __future__ import annotations

import random
import wave
from pathlib import Path

from server.tts.engine import TTSEngine

PHRASES_WAKE = [
    "在的，请讲。", "我在听。", "嗯，说吧。", "请吩咐。",
    "听着呢。", "在。", "请说。", "嗯？",
]
PHRASES_FAREWELL = [
    "再见。", "下次见。", "好，去休息了。", "随时叫我。",
    "再见啦。", "辛苦了，下次见。",
]


class VoicePacks:
    def __init__(self, engine: TTSEngine):
        self.engine = engine
        self._last: dict[str, str] = {}

    def ensure(self, phrases: list[str] | None = None) -> int:
        """预合成全部应答短句（写入引擎缓存）。返回成功条数。"""
        phrases = phrases or (PHRASES_WAKE + PHRASES_FAREWELL)
        ok = 0
        for p in phrases:
            try:
                self.engine.synth(p)
                ok += 1
            except Exception:
                pass
        return ok

    def _pick(self, kind: str, phrases: list[str]) -> str:
        choices = [p for p in phrases if p != self._last.get(kind)]
        pick = random.choice(choices or phrases)
        self._last[kind] = pick
        return pick

    def wake_phrase(self) -> str:
        return self._pick("wake", PHRASES_WAKE)

    def farewell_phrase(self) -> str:
        return self._pick("farewell", PHRASES_FAREWELL)

    def wake_pcm(self) -> tuple:
        return self.engine.synth(self.wake_phrase())

    def farewell_pcm(self) -> tuple:
        return self.engine.synth(self.farewell_phrase())
