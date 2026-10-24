"""声纹门控：eres2net 嵌入 + 余弦相似度。

- enroll：向导录 3 遍 → 均值嵌入存 settings.speaker_embeddings。
- verify(samples) -> (score, ok)；未注册时 (1.0, True)（门控降级为直通）。
"""
from __future__ import annotations

import numpy as np
import sherpa_onnx

from server.config import MODELS_DIR, load_settings, save_settings


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class SpeakerGate:
    def __init__(self, threshold: float | None = None):
        self.settings = load_settings()
        self.threshold = (
            threshold if threshold is not None
            else float(self.settings.get("speaker_threshold", 0.55))
        )
        self._ex = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(MODELS_DIR / "speaker-eres2net"
                          / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"),
                num_threads=1,
                provider="cpu",
            )
        )

    # ------------------------------------------------------------ 嵌入
    def embed(self, samples: np.ndarray) -> np.ndarray | None:
        """float32 [-1,1] → 嵌入向量。静音/过短返回 None。"""
        if samples.size < 16000 * 0.4:  # <0.4s 不可靠
            return None
        stream = self._ex.create_stream()
        stream.accept_waveform(16000, samples.astype(np.float32))
        emb: list[float] | None = None
        while self._ex.is_ready(stream):
            emb = self._ex.compute(stream)  # 每次返回当前完整嵌入，取最后一次
        if emb is None:
            return None
        return np.array(emb, dtype=np.float32)

    # ------------------------------------------------------------ 注册/校验
    def enrolled(self) -> bool:
        return bool(self.settings.get("speaker_embeddings"))

    def enroll(self, samples_list: list[np.ndarray]) -> bool:
        """多遍录音取均值，存 settings。至少一遍成功。"""
        embs = [e for e in (self.embed(s) for s in samples_list) if e is not None]
        if not embs:
            return False
        mean = np.mean(embs, axis=0)
        save_settings({"speaker_embeddings": mean.tolist()})
        self.settings = load_settings()
        return True

    def clear_enrollment(self) -> None:
        save_settings({"speaker_embeddings": []})
        self.settings = load_settings()

    def verify(self, samples: np.ndarray) -> tuple[float, bool]:
        """返回 (相似度, 是否本人)。未注册直通。"""
        stored = self.settings.get("speaker_embeddings")
        if not stored:
            return 1.0, True
        emb = self.embed(samples)
        if emb is None:
            return 0.0, False
        score = _cosine(emb, np.array(stored, dtype=np.float32))
        return score, score >= self.threshold
