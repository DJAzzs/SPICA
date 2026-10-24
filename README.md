# SPICA

语音优先的本地 Agent 操控台 —— 唤醒词 + 声纹门控 + 流式识别 + 提示词改写 + DSH 底座执行 + 本地 Qwen3-TTS 逐步播报。目标：不动键盘鼠标完成一次 Agent 任务。

## 架构

- **web/**：浏览器 UI（Vite + TS + React + Three.js）。麦克风采集 / TTS 播放 / 等距四状态可视化（见 `docs/design/effect-layer-spec.md`）。
- **server/**：Python Orchestrator（FastAPI，127.0.0.1）。语音管线（sherpa-onnx：silero-VAD + 流式 Zipformer 中英 + SenseVoice 精修 + 声纹门控）、两段式提示词改写、难度路由、DSH Agent 桥（`dsh --profile sdk`）、TTS 播报、优雅关停。
- **DSH**：`@deepseek-ai/dsh` 的 `sdk`（主会话，JSON-RPC）与 `headless`（一次性子任务）profile。

## 快速开始

```sh
make deps        # .venv + 清华源装依赖
make models      # 下载 sherpa-onnx 四模型到 models/
make check       # 环境自检
make up          # 启动服务 http://127.0.0.1:8666
make killall     # 清扫全部子进程
```

## 默认语音指令

| 词 | 动作 |
|---|---|
| "Hey, SPICA" / "嘿SPICA" | 唤醒（声纹门控，非本人静默） |
| "暂停" / "继续" | 暂停当前任务 / 恢复同会话 |
| "Bye, SPICA" / "拜拜SPICA" | 存档并优雅关停 |

所有词可自定义，每条带混淆变体表。

## 目录

```
server/   Python Orchestrator（voice/agent/tts/ws/control/lifecycle）
web/      前端（scene/hud/audioworklet/diagnose/review/wizard/settings）
docs/     设计规范（effect-layer-spec.md 为硬约束）
models/   下载的 asr/vad/声纹模型（gitignore）
```
