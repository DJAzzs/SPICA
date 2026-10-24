"""SPICA 全局配置与用户设置持久化。

路径全部相对项目根目录；用户可改项存 run/settings.json（首启向导/设置页写入）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
RUN_DIR = ROOT / "run"
ARCHIVES_DIR = ROOT / "archives"
ASSETS_DIR = ROOT / "assets"
WORKSPACE_DIR = ROOT / "workspace"
SETTINGS_FILE = RUN_DIR / "settings.json"
PROCS_FILE = RUN_DIR / "procs.json"

# ---------------------------------------------------------------- 词表默认值
# 每条：phrase 主词形；variants 混淆变体表（ASR 常见误识别，向导可增删）。
DEFAULT_WAKE_WORDS: list[dict] = [
    {
        "phrase": "Hey, SPICA",
        "variants": [
            "hey spica", "hi spica", "hey speaker", "hey spiker", "hey spyder",
            "嘿spica", "嘿思必卡", "嘿斯必卡", "嘿丝必卡", "a spica",
        ],
        "enabled": True,
    },
    {
        "phrase": "嘿SPICA",
        "variants": [
            "嘿 spica", "嘿思必卡", "嘿斯必卡", "嘿丝必卡", "黑spica", "嗨spica",
        ],
        "enabled": True,
    },
]

DEFAULT_FAREWELL_WORDS: list[dict] = [
    {
        "phrase": "Bye, SPICA",
        "variants": [
            "bye spica", "bye speaker", "bye spiker", "by spica",
            "拜拜spica", "拜拜斯必卡", "拜拜丝必卡",
        ],
        "enabled": True,
    },
    {
        "phrase": "拜拜SPICA",
        "variants": [
            "拜拜 spica", "拜拜斯必卡", "拜拜丝必卡",
            "白白spica", "白白斯必卡", "拜拜思必卡",
        ],
        "enabled": True,
    },
]

# 语义指令（暂停/继续/确认）——pipeline 语义机用，同样可自定义。
DEFAULT_COMMANDS: dict[str, list[str]] = {
    "pause": ["暂停", "先停一下", "停一下", "暂停一下", "先暂停"],
    "resume": ["继续", "继续执行", "接着做", "继续任务"],
    "confirm": ["确定", "确认", "是的", "对", "好"],
    "cancel": ["取消", "不了", "不用了", "算了"],
}

# ---------------------------------------------------------------- TTS 音色预设
# VoiceDesign 模型：音色=自然语言描述。预设若干命名音色，向导可改可自定义。
DEFAULT_VOICE_PRESETS: dict[str, str] = {
    "清朗助理": "一位年轻女性的声音，清亮、温和、语速平稳，像专业助理",
    "沉稳管家": "一位中年男性的声音，低沉、沉稳、让人安心，像英式管家",
    "少年灵音": "一位少年的声音，明亮、轻盈、略带好奇，语速稍快",
}

DEFAULT_SETTINGS = {
    "wake_words": DEFAULT_WAKE_WORDS,
    "farewell_words": DEFAULT_FAREWELL_WORDS,
    "commands": DEFAULT_COMMANDS,
    # 声纹门控：余弦相似度阈值；enrolled_embeddings 在向导完成后写入
    "speaker_gate_enabled": True,
    "speaker_threshold": 0.55,
    "speaker_embeddings": [],          # list[float] 列表（多遍注册取均值后再存）
    # ASR
    "asr_partial_debounce_ms": 300,
    # DSH / LLM（同一 provider：zai-coding-cn / glm-5.3，与 web profile 一致）
    "dsh_bin": "",                     # 空=自动探测 dsh / npx dsh
    "llm_base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
    "llm_api_key": "",                 # 空=env ZAI_CODING_CN_API_KEY 或 ~/.dsh/.credentials.yaml
    "llm_model_rewrite": "glm-5.3",
    "llm_model_route": "glm-5.3",
    # 难度 → DSH 路由（InitializeParams: model/reasoningEffort，glm-5.3 适配器）
    "difficulty_routes": {
        "simple":   {"model": "glm-5.3", "reasoning_effort": "low"},
        "normal":   {"model": "glm-5.3", "reasoning_effort": None},
        "complex":  {"model": "glm-5.3", "reasoning_effort": "max"},
    },
    # TTS
    "tts_model_path": "/home/dja/桌面/Models/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "tts_voice_preset": "清朗助理",
    "tts_custom_description": "",
    "tts_language": "Chinese",
    "tts_device": "auto",              # auto|cuda|cpu
    # 服务
    "host": "127.0.0.1",
    "port": 8666,
    # 行为
    "archive_git_commit": True,        # 结束词存档时 workspace 若为 git 仓库则 commit
    "wake_gate_during_tts_ms": 1200,   # TTS 播放期及结束后短暂关闭唤醒匹配
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _sanitize(merged: dict) -> dict:
    """防御：词表为 None/空时回退默认（避免 None 污染管线匹配）。"""
    if not merged.get("wake_words"):
        merged["wake_words"] = DEFAULT_WAKE_WORDS
    if not merged.get("farewell_words"):
        merged["farewell_words"] = DEFAULT_FAREWELL_WORDS
    return merged


def load_settings() -> dict:
    """读 run/settings.json，深合并到默认值。"""
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text("utf-8"))
        except Exception:
            data = {}
    return _sanitize(deep_merge(DEFAULT_SETTINGS, data))


def save_settings(patch: dict) -> dict:
    """合并写入并返回新设置。"""
    current = load_settings()
    merged = deep_merge(current, patch)
    # 过滤显式 None（避免覆盖为 null）
    for k in list(merged.keys()):
        if merged[k] is None and k != "reasoning_effort":
            if k in DEFAULT_SETTINGS:
                merged[k] = DEFAULT_SETTINGS[k]
    merged = _sanitize(merged)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), "utf-8"
    )
    return merged


def env_or_settings(settings: dict, key: str, env_names: tuple[str, ...]) -> str:
    """环境变量优先于 settings（不落盘敏感信息到日志）。"""
    for name in env_names:
        if os.environ.get(name):
            return os.environ[name]
    return settings.get(key) or ""
