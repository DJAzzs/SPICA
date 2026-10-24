"""TTS 冒烟：合成一句话到 assets/voices/_smoke.wav。 make tts-smoke"""
import time
import wave
from pathlib import Path

from server.config import ASSETS_DIR
from server.tts.engine import TTSEngine


def main() -> int:
    eng = TTSEngine()
    text = "SPICA 语音系统已就绪，随时待命。"
    t0 = time.time()
    pcm, sr = eng.synth(text)
    dt = time.time() - t0
    out = ASSETS_DIR / "voices" / "_smoke.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    print(
        f"[tts-smoke] 设备={'cuda' if __import__('torch').cuda.is_available() else 'cpu'} "
        f"合成用时={dt:.1f}s 时长={len(pcm)/sr:.1f}s 采样率={sr} 输出={out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
