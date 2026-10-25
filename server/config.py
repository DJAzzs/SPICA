"""SPICA 全局配置与用户设置持久化。

路径全部相对项目根目录；用户可改项存 run/settings.json（首启向导/设置页写入）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_ROOT = ROOT / "models"
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
            "hey spicka", "hey speca", "hey pica", "a spica", "hey, spica",
            "嘿spica", "嘿思必卡", "嘿斯必卡", "嘿斯皮卡", "嘿丝必卡",
            "嗨spica", "嗨思必卡",
        ],
        "enabled": True,
    },
    {
        "phrase": "嘿SPICA",
        "variants": [
            "嘿 spica", "嘿思必卡", "嘿斯必卡", "嘿斯皮卡", "嘿丝必卡",
            "黑spica", "嗨spica", "hey spica",
        ],
        "enabled": True,
    },
    {
        "phrase": "嘿，麦星",
        "variants": [
            "嘿麦星", "嘿 麦星", "黑麦星", "嗨麦星", "嘿迈星",
            "嘿卖星", "嘿脉星", "嘿麦心",
        ],
        "enabled": True,
    },
]

DEFAULT_FAREWELL_WORDS: list[dict] = [
    {
        "phrase": "Bye, SPICA",
        "variants": [
            "bye spica", "bye speaker", "bye spiker", "by spica", "bye spicka",
            "拜拜spica", "拜拜斯必卡", "拜拜丝必卡", "拜拜speaker",
        ],
        "enabled": True,
    },
    {
        "phrase": "拜拜SPICA",
        "variants": [
            "拜拜 spica", "拜拜斯必卡", "拜拜丝必卡", "拜拜斯皮卡",
            "白白spica", "白白斯必卡", "拜拜思必卡",
        ],
        "enabled": True,
    },
    {
        "phrase": "拜拜，麦星",
        "variants": [
            "拜拜麦星", "拜拜 麦星", "白白麦星", "拜拜迈星",
            "拜拜卖星", "拜拜脉星", "拜拜麦心",
        ],
        "enabled": True,
    },
]

# 语义指令（暂停/继续/确认）——pipeline 语义机用，同样可自定义。
# SPICA 内置身份（自我认知核心；设置页可查看，可整体覆盖）
SPICA_IDENTITY = """你是 SPICA——一位语音优先的本地 AI Agent 个人助理。
底层由 DeepSeek Harness（DSH）调度执行任务，当前由 {model} 模型驱动。
与其他 Agent 的不同：你以语音对话为主要交互方式；你越用越懂用户——拥有跨会话的
持久记忆、可自动积累的技能库、会学习用户音乐偏好；你的一切执行过程对用户完全透明
（逐步播报、权限需用户确认、全程可审计）。
你能帮用户：执行编程与系统任务、管理文件与工作区、多轮推进长期目标、播放音乐、
记忆偏好与知识。
回复风格：简洁、口语化（语音会被播报出来）、诚实，不说废话。"""

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
    # DSH / LLM（同一 provider：zai-coding-cn，默认 GLM-5.3-Flash 快速档）
    "dsh_bin": "",                     # 空=自动探测 dsh / npx dsh
    "llm_base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
    "llm_api_key": "",                 # 空=env ZAI_CODING_CN_API_KEY 或 ~/.dsh/.credentials.yaml
    "llm_model_rewrite": "glm-5.3-flash",
    "llm_model_route": "glm-5.3-flash",
    # 难度 → DSH 路由（InitializeParams: model/reasoningEffort，glm 适配器）
    "difficulty_routes": {
        "simple":   {"model": "glm-5.3-flash", "reasoning_effort": "low"},
        "normal":   {"model": "glm-5.3-flash", "reasoning_effort": None},
        "complex":  {"model": "glm-5.3-flash", "reasoning_effort": "max"},
    },
    # TTS
    "tts_model_path": "",  # 空=自动探测 models/Qwen3-TTS*/ 或设置绝对路径
    "tts_voice_preset": "清朗助理",
    "tts_custom_description": "",
    "tts_language": "Chinese",
    "tts_device": "auto",              # auto|cuda|cpu
    # 服务
    "host": "127.0.0.1",
    "port": 8666,
    # 行为
    "archive_git_commit": True,        # 结束词存档时 workspace 若为 git 仓库则 commit
    "wake_gate_during_tts_ms": 800,    # TTS 播放期及结束后短暂关闭匹配
    # （回声另有 narrator.echo_match 双保险，门控可短）
    # 任务执行偏好（追加到任务提示词，抑制滥用子代理；可在设置中关闭）
    "use_task_policy": True,
    "task_policy_suffix": (
        "\n\n（执行偏好：优先直接完成任务；非必要不派生子代理或并行任务，"
        "不重复委派；需要查看图片或文件时直接逐张读取后汇总。）"
    ),
    # 音乐（MusicFree / OpenSubsonic 兼容服务器）
    "musicfree_url": "http://127.0.0.1:14533",
    "musicfree_api_key": "",
    "musicfree_user": "admin",        # u/t/s 认证（无 API key 时使用）
    "musicfree_pass": "",
    "music_auto_on_task": False,   # Agent 任务开始时自动配乐（关键词由 flash 按任务选）
    # 人设 / SystemPrompt（每个任务前缀注入；空=不启用）
    "persona": "",
    # 身份覆盖（非空=完全替换内置 SPICA 身份；persona 仍追加）
    "identity_override": "",
    "custom_font": "",
    "custom_font_size": 0,
    # 长期目标
    "goal_max_rounds": 12,
    # 语音命令触发（关键词组：文本归一化后含组内全部关键词即命中）
    "slash_voice": {
        "export": [["导出", "会话"], ["导出", "对话"], ["导出", "zip"]],
        "compact": [["压缩", "会话"], ["压缩", "上下文"], ["清理", "上下文"],
                    ["压缩", "对话"]],
        "plan": [["只做", "计划"], ["计划", "模式"], ["先做", "规划"],
                 ["只要", "计划"]],
        "goal": [["制定", "目标"], ["设定", "目标"], ["长期", "目标"]],
        "goal_stop": [["停止", "目标"], ["取消", "目标"], ["结束", "目标"]],
        "memory_add": [["记住"]],
        "music_play": [["放首", "歌"], ["来点", "音乐"], ["播放", "音乐"],
                       ["放", "音乐"], ["来首", "歌"], ["放一首"]],
        "music_stop": [["停止", "音乐"], ["关掉", "音乐"], ["别放", "音乐"],
                       ["音乐", "停"]],
    },
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
