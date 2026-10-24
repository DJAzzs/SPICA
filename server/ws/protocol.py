"""SPICA WebSocket 协议：server ↔ web 客户端。

约定：
- 文本帧 = JSON 事件 {"t": <类型>, ...字段}
- 二进制帧 = 音频：默认 client→server 16kHz mono int16 LE PCM（麦克风流）；
  server→client 24kHz mono int16 LE PCM 分片（TTS 播报流，标记见 tts.chunk 事件）。
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------- server→client
# 状态机：idle → wake → listen → rewrite → exec → done → idle；paused 可从 exec 进入
EVENT_TYPES = {
    "state",          # {s: idle|wake|listen|rewrite|exec|paused|done|shutdown}
    "wake_ack",       # {accepted: bool, speaker_ok: bool, score: float}
    "partial",        # {text} ASR 增量（声纹线用；不逐字展示）
    "final",          # {text} SenseVoice 终稿
    "rewrite",        # {stage: draft|final, text, difficulty}
    "route",          # {model, reasoning_effort, difficulty} DSH 初始化选择
    "step",           # {i, summary, status: start|ok|fail}（场景动画用，瘦）
    "msg",            # {role: user|assistant|tool|system, text} 对话流富消息
    "tts",            # {speaking: bool, text} 播报开始/结束
    "task_done",      # {summary} 任务完成（完成呼吸动画+喊人）
    "paused", "resumed",
    "confirm_ask",    # {q, kind: shutdown|...} 需要用户语音确认
    "shutdown",       # 服务即将自停，前端展示告别画面
    "archive_done",   # {path} 存档完成
    "error",          # {message, fatal: bool}
    "settings",       # 当前设置快照（连接时下发）
    "diag",           # 硬件/环境诊断报告
    "level",          # {rms} 麦克风电平（诊断页/声纹线校准）
}

# ---------------------------------------------------------------- client→server
CLIENT_TYPES = {
    "mic",            # {on: bool, device_id?}
    "audio_meta",     # {sample_rate, channels}
    "text_input",     # {text} 键盘输入（与语音同管线分发）
    "manual_listen",  # {} 手动开启语音输入（唤醒词不可用时的兜底入口）
    "settings_patch", # {…} 设置更新
    "enroll_start", "enroll_add", "enroll_finish",  # 声纹注册流程
    "voice_preview",  # {text?} 音色试听
    "wake_test",      # {text} 手动注入文本测唤醒匹配（向导校准）
    "review_get",     # 拉取审阅模式所需最近任务全文
    "shutdown_now",   # 手动关停按钮
    "ping",
}


def ev(t: str, **fields: Any) -> dict:
    if t not in EVENT_TYPES and t not in CLIENT_TYPES:
        raise ValueError(f"未知事件类型: {t}")
    return {"t": t, **fields}
