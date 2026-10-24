"""silero VAD 分段（sherpa-onnx VoiceActivityDetector 封装）。

- feed(f32 chunk) 流式喂入；段落完成后回调（front/pop 模型）。
- flush() 用于流结束时强制结算尾部。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import sherpa_onnx

from server.config import MODELS_DIR


@dataclass
class Segment:
    start_sample: int
    samples: np.ndarray  # float32 [-1,1]


class VAD:
    def __init__(self, threshold: float = 0.5, min_silence: float = 0.6,
                 min_speech: float = 0.25, buffer_seconds: int = 60):
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(MODELS_DIR / "silero-vad" / "silero_vad.onnx")
        config.silero_vad.threshold = threshold
        config.silero_vad.min_silence_duration = min_silence
        config.silero_vad.min_speech_duration = min_speech
        config.sample_rate = 16000
        config.debug = False
        config.provider = "cpu"
        self._vad = sherpa_onnx.VoiceActivityDetector(
            config, buffer_size_in_seconds=buffer_seconds
        )

    def feed(self, chunk: np.ndarray) -> list[Segment]:
        """喂入 float32 chunk，返回本轮结算出的完整语音段。

        注意：sherpa-onnx 1.10.46 的 silero VAD 对超大块处理有 bug
        （一次性 accept 大段静音不结算段落），内部统一按 512 采样切片喂。
        """
        data = chunk.astype(np.float32)
        out: list[Segment] = []
        for i in range(0, data.size, 512):
            self._vad.accept_waveform(data[i:i + 512])
            out += self._drain()
        return out

    def flush(self) -> list[Segment]:
        self._vad.flush()
        return self._drain()

    def _drain(self) -> list[Segment]:
        out: list[Segment] = []
        while not self._vad.empty():
            front = self._vad.front
            out.append(Segment(int(front.start), np.array(front.samples, dtype=np.float32)))
            self._vad.pop()
        return out
