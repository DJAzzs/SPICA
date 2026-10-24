"""环境自检：make check。逐项 PASS/FAIL，致命项失败退出码 1。"""
from __future__ import annotations

import re
import shutil
import socket
import sys
from pathlib import Path

from server.config import MODELS_DIR, ROOT, load_settings

DSH_NPX_BIN = Path(
    "/home/dja/.npm/_npx/b86ed90107c62dab/node_modules/.bin/dsh"
)
CRED_FILE = Path.home() / ".dsh" / ".credentials.yaml"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "", fatal: bool = True) -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL' if fatal else 'WARN'}] {name}"
          f"{(' — ' + detail) if detail else ''}")


def main() -> int:
    settings = load_settings()
    print("== SPICA 环境自检 ==")

    # Python / 包
    check("Python 3.12 venv", sys.version_info[:2] == (3, 12),
          sys.version.split()[0])
    try:
        import sherpa_onnx
        check("sherpa-onnx", True, sherpa_onnx.__version__, fatal=False)
    except Exception as e:
        check("sherpa-onnx", False, str(e))
    try:
        import torch
        check("torch", True, f"{torch.__version__} cuda={torch.cuda.is_available()}",
              fatal=False)
    except Exception as e:
        check("torch", False, str(e))
    try:
        import qwen_tts  # noqa: F401
        check("qwen-tts", True, "", fatal=False)
    except Exception as e:
        check("qwen-tts", False, str(e))

    # 模型
    required = [
        "silero-vad/silero_vad.onnx",
        "streaming-zipformer-zh-en/encoder-epoch-99-avg-1.int8.onnx",
        "streaming-zipformer-zh-en/decoder-epoch-99-avg-1.int8.onnx",
        "streaming-zipformer-zh-en/joiner-epoch-99-avg-1.int8.onnx",
        "streaming-zipformer-zh-en/tokens.txt",
        "sense-voice/model.int8.onnx",
        "sense-voice/tokens.txt",
        "speaker-eres2net/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
    ]
    for rel in required:
        check(f"模型 {rel}", (MODELS_DIR / rel).exists())

    # TTS 模型
    tts_path = Path(settings["tts_model_path"])
    check("Qwen3-TTS 模型目录", tts_path.exists() and (tts_path / "model.safetensors").exists())

    # dsh
    dsh = shutil.which("dsh") or (str(DSH_NPX_BIN) if DSH_NPX_BIN.exists() else "")
    check("dsh 可执行", bool(dsh), dsh)

    # LLM 凭据（zai-coding-cn，与 DSH 同源）
    key = ""
    if CRED_FILE.exists():
        m = re.search(r"ZAI_CODING_CN_API_KEY:\s*(\S+)", CRED_FILE.read_text())
        if m:
            key = m.group(1)
    import os
    key = os.environ.get("ZAI_CODING_CN_API_KEY") or key
    check("LLM 凭据 (zai-coding-cn)", bool(key),
          "环境变量或 ~/.dsh/.credentials.yaml" if key else "未找到，语音改写将不可用")

    # 端口
    port = int(settings.get("port", 8666))
    try:
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((settings.get("host", "127.0.0.1"), port))
        check(f"端口 {port} 可用", True)
    except OSError as e:
        check(f"端口 {port} 可用", False, str(e))

    fatal = [r for r in RESULTS if not r[1]]
    print(f"== 自检完成：{len(RESULTS)-len(fatal)}/{len(RESULTS)} 通过 ==")
    return 1 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(main())
