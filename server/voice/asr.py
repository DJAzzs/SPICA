"""双引擎 ASR：流式 Zipformer（partials）+ SenseVoice（整段精修终稿）。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import sherpa_onnx

from server.config import MODELS_DIR

_ZIPF = MODELS_DIR / "streaming-zipformer-zh-en"
_SV = MODELS_DIR / "sense-voice"


class StreamingASR:
    """常开流式识别：feed → partial；每段开始 reset()。"""

    def __init__(self, num_threads: int = 2):
        self.rec = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(_ZIPF / "tokens.txt"),
            encoder=str(_ZIPF / "encoder-epoch-99-avg-1.int8.onnx"),
            decoder=str(_ZIPF / "decoder-epoch-99-avg-1.int8.onnx"),
            joiner=str(_ZIPF / "joiner-epoch-99-avg-1.int8.onnx"),
            num_threads=num_threads,
            sample_rate=16000,
            feature_dim=80,
            provider="cpu",
        )
        self.stream = self.rec.create_stream()

    def reset(self) -> None:
        """新语音段：开新流（旧流状态丢弃）。"""
        self.stream = self.rec.create_stream()

    def feed(self, chunk: np.ndarray, decode: bool = True) -> str:
        """喂 float32 chunk；decode=True 时返回当前 partial 文本。"""
        self.stream.accept_waveform(16000, chunk.astype(np.float32))
        if decode and self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)
            return self.rec.get_result(self.stream)
        return ""


class SenseVoiceASR:
    """非流式整段识别：断句后的高精度终稿。"""

    def __init__(self, num_threads: int = 2, language: str = "auto"):
        self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(_SV / "model.int8.onnx"),
            tokens=str(_SV / "tokens.txt"),
            num_threads=num_threads,
            language=language,
            use_itn=True,
        )

    def transcribe(self, samples: np.ndarray) -> str:
        if samples.size == 0:
            return ""
        stream = self.rec.create_stream()
        stream.accept_waveform(16000, samples.astype(np.float32))
        self.rec.decode_stream(stream)
        return stream.result.text.strip()
