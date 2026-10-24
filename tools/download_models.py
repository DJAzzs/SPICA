"""下载 SPICA 所需的四个 sherpa-onnx 模型到 models/（国内 hf-mirror 源）。

源映射（GitHub 不可达时的国内镜像；均经 hf-mirror 验证）：
  - silero-vad        deepghs/silero-vad-onnx
  - streaming zipformer csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20 (int8)
  - sense-voice       csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17 (int8)
  - speaker eres2net  onemira/eres2net-base-3dspeaker-onnx
用法：make models 或 .venv/bin/python -m tools.download_models
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

from server.config import MODELS_DIR

MIRROR = "https://hf-mirror.com"

FILES: dict[str, dict] = {
    # 相对 models/ 的目标路径 → {url, min_mb}
    "silero-vad/silero_vad.onnx": {
        "url": f"{MIRROR}/deepghs/silero-vad-onnx/resolve/main/silero_vad.onnx",
        "min_mb": 1.0,
    },
    "streaming-zipformer-zh-en/encoder-epoch-99-avg-1.int8.onnx": {
        "url": f"{MIRROR}/csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/resolve/main/encoder-epoch-99-avg-1.int8.onnx",
        "min_mb": 30,
    },
    "streaming-zipformer-zh-en/decoder-epoch-99-avg-1.int8.onnx": {
        "url": f"{MIRROR}/csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/resolve/main/decoder-epoch-99-avg-1.int8.onnx",
        "min_mb": 0.3,
    },
    "streaming-zipformer-zh-en/joiner-epoch-99-avg-1.int8.onnx": {
        "url": f"{MIRROR}/csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/resolve/main/joiner-epoch-99-avg-1.int8.onnx",
        "min_mb": 0.1,
    },
    "streaming-zipformer-zh-en/tokens.txt": {
        "url": f"{MIRROR}/csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/resolve/main/tokens.txt",
        "min_mb": 0.05,
    },
    "sense-voice/model.int8.onnx": {
        "url": f"{MIRROR}/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.int8.onnx",
        "min_mb": 100,
    },
    "sense-voice/tokens.txt": {
        "url": f"{MIRROR}/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/tokens.txt",
        "min_mb": 0.3,
    },
    "speaker-eres2net/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx": {
        "url": f"{MIRROR}/onemira/eres2net-base-3dspeaker-onnx/resolve/main/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
        "min_mb": 20,
    },
}

# 单测夹具（小 wav，放 tests/fixtures/）
FIXTURES: dict[str, str] = {
    "zh.wav": f"{MIRROR}/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/test_wavs/zh.wav",
    "en.wav": f"{MIRROR}/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/test_wavs/en.wav",
}


def _download(url: str, dest: Path, min_mb: float) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "spica/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
            total = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
                mb = total / 1e6
                if int(mb * 4) % 2 == 0:
                    print(f"\r    {dest.name}: {mb:.1f}MB", end="", flush=True)
    except Exception as e:
        print(f"\n  [失败] {dest.name}: {e}")
        tmp.unlink(missing_ok=True)
        return False
    print(f"\r    {dest.name}: {total/1e6:.1f}MB 用时 {time.time()-t0:.0f}s")
    if total < min_mb * 1e6:
        print(f"  [校验失败] {dest.name} 小于 {min_mb}MB，删除重下")
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dest)
    return True


def main() -> int:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = MODELS_DIR / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except Exception:
            manifest = {}

    ok = True
    for rel, spec in FILES.items():
        dest = MODELS_DIR / rel
        if dest.exists() and dest.stat().st_size > spec["min_mb"] * 1e6:
            print(f"  [已有] {rel}")
            continue
        print(f"  [下载] {rel}")
        if not _download(spec["url"], dest, spec["min_mb"]):
            ok = False
            continue
        manifest[rel] = {
            "url": spec["url"],
            "bytes": dest.stat().st_size,
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()[:16],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), "utf-8")

    # 单测夹具
    fixdir = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    for name, url in FIXTURES.items():
        dest = fixdir / name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"  [下载] tests/fixtures/{name}")
            _download(url, dest, 0.01)

    print("[models] 完成" if ok else "[models] 存在失败项，可重跑续传")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
