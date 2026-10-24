"""语音管线状态机：常开线程消费麦克风流。

状态：
  DORMANT  休眠侦听（唤醒/结束词扫描）
  LISTENING 唤醒后收指令（含 followup 窗口内的连续对话）

每 chunk（16k mono int16 bytes，来自 WS）：
  1. 电平事件（节流 100ms）
  2. silero VAD 喂入 → 结算完整段
  3. 流式 Zipformer 连续解码 → partial（DORMANT 时用于快速唤醒命中，
     LISTENING 时用于改写预热）
段结算（VAD 给出完整段）：
  - SenseVoice 终稿 → 唤醒/结束/语义指令匹配 → 回调
唤醒快速路径：partial 命中唤醒词即回 ack（不等段结束，延迟≈partial 节拍），
声纹用环形缓冲取唤醒词前后的音频窗校验。

回调全部在工作线程触发；asyncio 侧需自行 marshal。
"""
from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from server.config import load_settings
from server.voice.asr import SenseVoiceASR, StreamingASR
from server.voice.vad import Segment, VAD
from server.voice.wake import Matcher, command_entries
from server.voice.speaker import SpeakerGate

SR = 16000


@dataclass
class PipelineCallbacks:
    on_level: Callable[[float], None] = lambda r: None
    on_wake: Callable[[str, bool, float], None] = lambda phrase, ok, score: None
    on_partial: Callable[[str], None] = lambda t: None      # LISTENING 中的增量
    on_final: Callable[[str], None] = lambda t: None        # 终稿（已去唤醒词）
    on_farewell: Callable[[str], None] = lambda phrase: None
    on_command: Callable[[str, str], None] = lambda name, text: None


@dataclass
class _State:
    mode: str = "DORMANT"          # DORMANT | LISTENING
    followup_until: float = 0.0    # LISTENING 保持到（时间戳）
    tts_gate_until: float = 0.0    # TTS 播报期抑制匹配
    wake_hit_until: float = 0.0    # 唤醒去抖
    last_level_ts: float = 0.0


class VoicePipeline:
    def __init__(self, settings: dict | None = None,
                 callbacks: PipelineCallbacks | None = None,
                 speaker: SpeakerGate | None = None,
                 start: bool = True):
        self.settings = settings or load_settings()
        self.cb = callbacks or PipelineCallbacks()
        self.matcher = Matcher()
        self.wake_words = self.settings.get("wake_words", [])
        self.farewell_words = self.settings.get("farewell_words", [])
        self.commands = command_entries(self.settings.get("commands", {}))
        self.speaker = speaker or SpeakerGate()
        self.vad = VAD(
            min_silence=float(self.settings.get("vad_min_silence", 0.6)),
        )
        self.stream_asr = StreamingASR()
        self.final_asr = SenseVoiceASR()
        self.st = _State()
        self._q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=200)
        self._ring: deque[np.ndarray] = deque()  # int16 chunks（声纹窗用）
        self._ring_samples = 0
        self._thread: threading.Thread | None = None
        if start:
            self.start()

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="voice-pipeline", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._q.put(None)

    def feed_pcm(self, data: bytes) -> None:
        """WS 二进制帧入口：int16 LE mono 16k。"""
        try:
            self._q.put_nowait(np.frombuffer(data, dtype=np.int16).copy())
        except queue.Full:
            pass  # 丢弃保实时

    def set_tts_gate(self, on: bool, hold_ms: int | None = None) -> None:
        """TTS 播放期抑制唤醒/结束词匹配（防自唤醒）。"""
        if on:
            self.st.tts_gate_until = time.time() + 1e9
        else:
            hold = (hold_ms if hold_ms is not None
                    else int(self.settings.get("wake_gate_during_tts_ms", 1200)))
            self.st.tts_gate_until = time.time() + hold / 1000.0

    def arm_listening(self, seconds: float = 12.0) -> None:
        """外部（如向导/确认对话）直接进入 LISTENING。"""
        self.st.mode = "LISTENING"
        self.st.followup_until = time.time() + seconds

    # ------------------------------------------------------------ 声纹窗
    def _push_ring(self, chunk_i16: np.ndarray) -> None:
        self._ring.append(chunk_i16)
        self._ring_samples += chunk_i16.size
        while self._ring_samples > SR * 4:  # 保留 4s
            drop = self._ring.popleft()
            self._ring_samples -= drop.size

    def _voice_window(self, seconds: float = 2.0) -> np.ndarray:
        take: list[np.ndarray] = []
        remain = int(seconds * SR)
        for c in reversed(self._ring):
            if remain <= 0:
                break
            take.append(c[-remain:] if c.size > remain else c)
            remain -= min(c.size, remain)
        if not take:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(take[::-1])

    # ------------------------------------------------------------ 主循环
    def _run(self) -> None:
        decode_every = 0.32  # partial 解码节拍
        last_decode = 0.0
        while True:
            item = self._q.get()
            if item is None:
                break
            i16 = item
            f32 = i16.astype(np.float32) / 32768.0

            # 电平（节流）
            now = time.time()
            if now - self.st.last_level_ts > 0.1:
                self.st.last_level_ts = now
                rms = float(np.sqrt(np.mean(np.square(i16.astype(np.float32)))) / 32768.0)
                self.cb.on_level(rms)

            self._push_ring(i16)

            # 流式识别
            decode = now - last_decode >= decode_every
            if decode:
                last_decode = now
            partial = self.stream_asr.feed(f32, decode=decode)
            if decode and partial:
                self._on_partial(partial)

            # VAD 段结算
            for seg in self.vad.feed(f32):
                self._on_segment(seg)
        # 流结束
        for seg in self.vad.flush():
            self._on_segment(seg)

    # ------------------------------------------------------------ partial
    def _gated(self) -> bool:
        return time.time() < self.st.tts_gate_until

    def _on_partial(self, text: str) -> None:
        if self._gated():
            return
        if self.st.mode == "DORMANT":
            hit = self.matcher.match_prefix(text, self.wake_words, "wake")
            if hit and time.time() > self.st.wake_hit_until:
                self.st.wake_hit_until = time.time() + 1.0
                self._handle_wake(hit, fast=True)
        else:
            # LISTENING：去唤醒词后的增量交给上层预热改写
            hit = self.matcher.match_prefix(text, self.wake_words, "wake")
            self.cb.on_partial(hit.remainder if hit and hit.remainder else text)

    # ------------------------------------------------------------ 唤醒
    def _handle_wake(self, hit, fast: bool,
                     samples: np.ndarray | None = None) -> None:
        """唤醒处理。samples=段结算时的完整音频（声纹更稳）；
        fast=True 来自 partial 路径（用环形缓冲窗）。"""
        if samples is not None and samples.size > 0:
            win = samples
        else:
            win = self._voice_window(2.0).astype(np.float32) / 32768.0
        score, ok = (1.0, True)
        if self.settings.get("speaker_gate_enabled", True) and self.speaker.enrolled():
            score, ok = self.speaker.verify(win)
        if not ok:
            return  # 非本人：静默（画面亦无反应）
        self.st.mode = "LISTENING"
        self.st.followup_until = time.time() + 12.0
        self.cb.on_wake(hit.phrase, True, score)
        # 唤醒词后紧跟指令（"Hey SPICA 帮我…"）
        if hit.remainder and len(hit.remainder) >= 2:
            if fast:
                self.cb.on_partial(hit.remainder)
            else:
                self.cb.on_final(hit.remainder)

    # ------------------------------------------------------------ 段结算
    def _on_segment(self, seg: Segment) -> None:
        text = self.final_asr.transcribe(seg.samples)
        if not text:
            self._after_utterance()
            return
        now = time.time()

        # DORMANT：唤醒兜底（句首命中优先级高于结束词——句首是更强意图）
        if self.st.mode == "DORMANT":
            hit = self.matcher.match_prefix(text, self.wake_words, "wake")
            if hit and not self._gated() and time.time() > self.st.wake_hit_until:
                self.st.wake_hit_until = time.time() + 1.0
                self._handle_wake(hit, fast=False, samples=seg.samples)
                self._after_utterance()
                return

        # 结束词（任意状态；过声纹门）
        fw = self.matcher.match_anywhere(text, self.farewell_words, "farewell")
        if fw and not self._gated():
            score, ok = (1.0, True)
            if self.settings.get("speaker_gate_enabled", True) and self.speaker.enrolled():
                score, ok = self.speaker.verify(seg.samples)
            if ok:
                self.cb.on_farewell(fw.phrase)
                return

        # 语义指令（暂停/继续/确认/取消）
        for name, entries in self.commands.items():
            if self.matcher.match_anywhere(text, entries, f"command:{name}"):
                self.cb.on_command(name, text)
                self._after_utterance()
                return

        if self.st.mode == "LISTENING":
            hit = self.matcher.match_prefix(text, self.wake_words, "wake")
            payload = hit.remainder if hit and hit.remainder else text
            if payload:
                self.cb.on_final(payload)
        self._after_utterance()

    def _after_utterance(self) -> None:
        self.stream_asr.reset()
        if self.st.mode == "LISTENING" and time.time() > self.st.followup_until:
            self.st.mode = "DORMANT"
