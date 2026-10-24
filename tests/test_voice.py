"""语音管线组件与集成测试（需 models/ 已下载；夹具 tests/fixtures/）。"""
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest

FIX = Path(__file__).parent / "fixtures"


def load_wav(name: str) -> np.ndarray:
    with wave.open(str(FIX / name), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def chunk_feed(pipeline, i16: np.ndarray, chunk=3200, silence_s=1.2):
    """模拟 WS 流：原始音频 + 尾部静音（触发 VAD 段结算）。"""
    for i in range(0, i16.size, chunk):
        pipeline.feed_pcm(i16[i:i + chunk].tobytes())
    pipeline.feed_pcm(np.zeros(int(16000 * silence_s), dtype=np.int16).tobytes())


# ---------------------------------------------------------------- VAD
def test_vad_segments():
    from server.voice.vad import VAD
    f = load_wav("zh.wav").astype(np.float32) / 32768.0
    vad = VAD()
    segs = []
    for i in range(0, f.size, 1600):
        segs += vad.feed(f[i:i + 1600])
    segs += vad.flush()
    assert len(segs) >= 1
    assert any(len(s.samples) > 16000 * 2 for s in segs)  # 至少一段 >2s


# ---------------------------------------------------------------- 双 ASR
def test_sense_voice_zh_en():
    from server.voice.asr import SenseVoiceASR
    sv = SenseVoiceASR()
    zh = sv.transcribe(load_wav("zh.wav").astype(np.float32) / 32768.0)
    en = sv.transcribe(load_wav("en.wav").astype(np.float32) / 32768.0)
    assert "开放时间" in zh and "9点" in zh          # ITN 数字归一化
    assert "chieftain" in en.lower()


def test_streaming_partials():
    from server.voice.asr import StreamingASR
    st = StreamingASR()
    f = load_wav("zh.wav").astype(np.float32) / 32768.0
    partials = []
    for i in range(0, f.size, 3200):
        p = st.feed(f[i:i + 3200], decode=True)
        if p and (not partials or p != partials[-1]):
            partials.append(p)
    while st.rec.is_ready(st.stream):
        st.rec.decode_stream(st.stream)
    final = st.rec.get_result(st.stream)
    assert len(partials) >= 3                          # 流式增量
    assert "开放时间" in final


# ---------------------------------------------------------------- 声纹
def test_speaker_self_similarity():
    from server.voice.speaker import SpeakerGate
    gate = SpeakerGate()
    f = load_wav("zh.wav").astype(np.float32) / 32768.0
    a, b = gate.embed(f[: f.size // 2]), gate.embed(f[f.size // 2:])
    assert a is not None and b is not None
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    score = float(np.dot(a, b) / (na * nb))
    assert score > 0.6                                 # 同一人两段
    assert gate.embed(f[: int(16000 * 0.2)]) is None   # 过短拒绝


# ---------------------------------------------------------------- 管线集成
class Recorder:
    def __init__(self):
        self.events: list[tuple] = []
        self.wake = threading.Event()
        self.final = threading.Event()
        self.farewell = threading.Event()

    def cb(self):
        from server.voice.pipeline import PipelineCallbacks
        return PipelineCallbacks(
            on_wake=lambda phrase, ok, score: (self.events.append(("wake", phrase, ok)),
                                               self.wake.set()),
            on_partial=lambda t: self.events.append(("partial", t)),
            on_final=lambda t: (self.events.append(("final", t)), self.final.set()),
            on_farewell=lambda phrase: (self.events.append(("farewell", phrase)),
                                        self.farewell.set()),
            on_command=lambda name, text: self.events.append(("command", name, text)),
        )


def make_pipeline(rec: Recorder, wake="开放时间", farewell="下午5点"):
    """用夹具转写内容里的词当唤醒/结束词（真实音频端到端）。"""
    from server.voice.pipeline import VoicePipeline
    settings = {
        "wake_words": [{"phrase": wake, "variants": [], "enabled": True}],
        "farewell_words": [{"phrase": farewell, "variants": [], "enabled": True}],
        "commands": {"pause": ["暂停"], "resume": ["继续"], "confirm": ["确定"], "cancel": ["取消"]},
        "speaker_gate_enabled": False,   # 测试环境未注册声纹，且省嵌入耗时
        "vad_min_silence": 0.6,
    }
    return VoicePipeline(settings=settings, callbacks=rec.cb())


def test_pipeline_wake_and_final():
    rec = Recorder()
    p = make_pipeline(rec)
    try:
        chunk_feed(p, load_wav("zh.wav"))
        assert rec.wake.wait(10), f"未唤醒 events={rec.events}"
        assert rec.final.wait(10), f"无终稿 events={rec.events}"
        kinds = [e[0] for e in rec.events]
        assert kinds.index("wake") < kinds.index("final")
        final = next(e[1] for e in rec.events if e[0] == "final")
        assert "早上" in final and "开放时间" not in final  # 终稿已剥离唤醒词
    finally:
        p.stop()


def test_pipeline_tts_gate_suppresses_wake():
    """TTS 播报期间唤醒匹配必须被抑制（防自唤醒）。"""
    rec = Recorder()
    p = make_pipeline(rec)
    try:
        p.set_tts_gate(True)
        chunk_feed(p, load_wav("zh.wav"))
        time.sleep(0.5)
        assert not rec.wake.is_set()
        # 门关（带 hold），hold 过后恢复匹配
        p.set_tts_gate(False, hold_ms=0)
        rec2 = Recorder()
        p.cb = rec2.cb()
        chunk_feed(p, load_wav("zh.wav"))
        assert rec2.wake.wait(10), f"门开后未唤醒 events={rec2.events}"
    finally:
        p.stop()


def test_pipeline_dormant_no_wake_for_ordinary_speech():
    rec = Recorder()
    p = make_pipeline(rec)
    try:
        chunk_feed(p, load_wav("en.wav"))                # 内容不含唤醒词
        time.sleep(0.5)
        assert not rec.wake.is_set()
        assert not rec.final.is_set()                    # DORMANT 不发 final
    finally:
        p.stop()


def test_pipeline_farewell():
    rec = Recorder()
    # 唤醒词用句中不存在的词，避免夹具句首唤醒优先级压过结束词
    p = make_pipeline(rec, wake="谢谢观看", farewell="下午5点")
    try:
        chunk_feed(p, load_wav("zh.wav"))
        assert rec.farewell.wait(10), f"未触发结束词 events={rec.events}"
    finally:
        p.stop()
