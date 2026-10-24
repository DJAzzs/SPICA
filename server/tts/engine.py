"""Qwen3-TTS-VoiceDesign 引擎（懒加载 + 磁盘缓存）。

- 预设音色 = 命名的音色描述（instruct）；自定义音色 = 用户描述。
- 缓存：.cache/tts/<sha256(text|instruct|lang)>.wav，16bit PCM。
- 设备 auto：cuda:0（bf16）→ cpu。模型路径来自 settings。
"""
from __future__ import annotations

import hashlib
import threading
import time
import wave
from pathlib import Path

import numpy as np

from server.config import DEFAULT_VOICE_PRESETS, ROOT, load_settings

CACHE_DIR = ROOT / ".cache" / "tts"


class TTSEngine:
    _model = None
    _lock = threading.Lock()

    def __init__(self, settings: dict | None = None):
        self.settings = settings or load_settings()

    # ------------------------------------------------------------ 加载
    def _load(self):
        with self._lock:
            if TTSEngine._model is not None:
                return TTSEngine._model
            import torch
            from qwen_tts import Qwen3TTSModel

            device = self.settings.get("tts_device", "auto")
            if device == "auto":
                device = "cuda:0" if torch.cuda.is_available() else "cpu"
            kwargs: dict = {"device_map": device}
            if str(device).startswith("cuda"):
                kwargs["dtype"] = torch.bfloat16
            t0 = time.time()
            TTSEngine._model = Qwen3TTSModel.from_pretrained(
                self.settings["tts_model_path"], **kwargs
            )
            print(f"[tts] 模型已加载：{device}，用时 {time.time()-t0:.1f}s")
            return TTSEngine._model

    # ------------------------------------------------------------ 音色
    def resolve_instruct(self) -> str:
        custom = (self.settings.get("tts_custom_description") or "").strip()
        if custom:
            return custom
        preset = self.settings.get("tts_voice_preset", "")
        return DEFAULT_VOICE_PRESETS.get(preset) or next(
            iter(DEFAULT_VOICE_PRESETS.values())
        )

    @staticmethod
    def supported_speakers() -> list[str]:
        model = TTSEngine._model
        if model is None:
            return []
        try:
            return list(model.get_supported_speakers())
        except Exception:
            return []

    # ------------------------------------------------------------ 合成
    def _cache_path(self, text: str, instruct: str, lang: str) -> Path:
        key = hashlib.sha256(
            f"{text}|{instruct}|{lang}".encode("utf-8")
        ).hexdigest()[:32]
        return CACHE_DIR / f"{key}.wav"

    def synth(self, text: str, instruct: str | None = None,
              language: str | None = None) -> tuple[np.ndarray, int]:
        """返回 (int16 mono ndarray, sample_rate)。命中缓存零延迟。"""
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.int16), 24000
        lang = language or self.settings.get("tts_language", "Chinese")
        voice = instruct or self.resolve_instruct()
        cache = self._cache_path(text, voice, lang)

        if cache.exists():  # 缓存命中
            with wave.open(str(cache), "rb") as w:
                sr = w.getframerate()
                data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            return data, sr

        model = self._load()
        wavs, sr = model.generate_voice_design(
            text=text, instruct=voice, language=lang, non_streaming_mode=True
        )
        audio = np.asarray(wavs[0], dtype=np.float32)
        audio = np.clip(audio, -1.0, 1.0)
        pcm = (audio * 32767).astype(np.int16)

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with wave.open(str(cache), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        return pcm, sr
