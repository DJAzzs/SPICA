# SPICA

**语音优先的本地 Agent 操控台** —— 像贾维斯一样对话：唤醒词 + 声纹门控 + 流式识别 + AI 提示词改写 + DSH 底座执行 + 本地 Qwen3-TTS 逐步播报 + 自动配乐。目标：不动键盘鼠标完成一次 Agent 任务，而且它**越用越懂你**（记忆 / 技能 / 音乐偏好持续自进化）。

```
你："Hey, SPICA，帮我在工作区建一个爬虫项目骨架"
SPICA："收到，开始。" →（每步一句播报，音乐自动压低）→"已完成，用时 1 分 23 秒"
你："Bye, SPICA" → 存档 → 告别语音 → 全部进程优雅退出
```

## 功能全景

**🎙 语音交互**
- 唤醒/结束词：内置 "Hey, SPICA" / "嘿SPICA" / "Bye, SPICA" / "拜拜SPICA"（可自定义 + 混淆变体表）
- 声纹门控：只回应注册者，他人静默；注册全程零 TTS（防自采）
- 双引擎 ASR：流式 Zipformer（中英）实时转写 + SenseVoice 整段精修；边说边改写（两段式：预热草稿 + 最小校正）
- 自回声免疫：播报期整段丢弃 + 回声文本匹配双保险（自己的声音永远不会变成任务）
- TTS 智能闪避：SPICA 说话/你说话，音乐 1 秒渐弱，结束 1 秒渐回

**🤖 Agent 能力（DSH 底座）**
- 难度路由：cheap LLM 分级 simple/normal/complex → 自动选模型与推理强度（reasoningEffort）
- 思考模型支持：灰色"思考中"实时滚动，可折叠；任务完成自动收起过程，只留总结（可展开）
- 计时：运行中"已用时 x分y秒"实时跳动，完成固化
- 插话队列、语音/按钮暂停恢复（SIGTERM + 持久化会话 resume）、执行偏好（抑制滥用子代理）

**🗂 会话系统**
- 自动命名（首个任务后 LLM 起名）、本地持久化、服务重启自动续接
- 历史/打开/删除/重命名，每会话独立**工作区**与**权限**（只读/工作区写入/完全访问）
- 导出 zip（session.md + events.jsonl）、`/compact` 上下文压缩（保留摘要续命）

**🧠 自进化（Hermes 式，全自动 + 可审计）**
- 有界记忆：MEMORY/USER 双文件（2200/1375 字符强制蒸馏），安全扫描（注入/凭据/零宽字符），每 5 轮自动 nudge 提炼，说"记住 xxx"直写
- 技能收获：复杂任务（≥5 工具调用）成功后自动提炼 SKILL 入库，任务提示词自动附技能索引（渐进披露），`/skills` 管理
- 全部自动写入记录在 `run/evolution-audit.jsonl`

**🎵 音乐系统（MusicFree / OpenSubsonic）**
- "放一首周杰伦的晴天"→ 远程搜索 → 自动下载入库 → 播放（顶部玻璃卡：封面/进度/控制）
- 描述选歌："来首英文摇滚"（LLM 翻译成具体歌名兜底）
- 偏好学习：70% 喜好加权（count^0.7，长尾有机会）+ 30% 探索，`/music taste` 看画像
- 任务自动配乐（可选）：flash 按任务气质选歌

**⌨️ 对话式 UI**
- DSH 式对话流（Markdown 渲染）+ 键盘输入（与语音同管线）
- 🎤 手动聆听按钮（唤醒不可用时的兜底，再点取消）、＋ 上传/拖拽上传到工作区
- 文件浏览器（会话工作区内，路径沙箱）、审阅模式
- 双主题：米白新拟物（默认）/ 钛黑液态玻璃，右上滑块切换，默认跟随系统

## 快速开始

```sh
make deps        # .venv（Python 3.12）+ 清华源装依赖
make models      # 下载 sherpa-onnx 四模型（hf-mirror）
make check       # 环境自检
make up          # 后台启动 → http://127.0.0.1:8666
make log         # 跟日志    make stop / status / killall
```

首次使用：页面点击授权麦克风 → 向导（声纹注册/唤醒词校准/音色试听）→ 说 "Hey, SPICA"。

**音乐**（可选）：部署 [MusicFree](docs/musicfree-setup.md)（Docker 一行）→ 装一个 RemoteSearch 插件 → 设置页填地址即可。

## 命令与语音

| 键盘命令 | 语音说法 | 作用 |
|---|---|---|
| `/plan <目标>` | "只做计划…" | 只读规划模式（单轮） |
| `/compact` | "压缩一下上下文" | LLM 压缩历史，新会话带摘要续命 |
| `/export` | "导出当前会话" | zip 下载 |
| `/goal <目标>` | "制定目标…" | 长期目标多轮推进（自动判定达成） |
| `/music <词/stop/next/taste>` | "放一首…/把音乐停了" | 音乐播放与偏好 |
| `/memory add/list/remove` | "记住 xxx" | 记忆管理 |
| `/skills list/del` | — | 技能库管理 |
| — | "暂停 / 继续" | 任务暂停恢复 |
| — | "Hey SPICA"（无任务时） | 唤醒应答（预生成语音包 <100ms） |

## 架构

```
web/     React + TS（Vite）：对话流/Markdown/思考折叠/计时、AudioWorklet 采集
         （AEC+任意采样率分数重采样）、WebAudio TTS 播放、音乐卡+ducking、
         新拟物/液态玻璃双主题、Three.js 光晕背景
server/  Python FastAPI（127.0.0.1:8666）
         voice/      silero-VAD → 唤醒匹配（拼音+模糊）→ 声纹 → 双ASR
         agent/      sdk_client(JSON-RPC) / 两段式改写 / 难度路由 / 语义状态机
         evolution/  有界记忆 + 技能收获（审计）
         media/      MusicFree(OpenSubsonic) + 偏好学习
         tts/        Qwen3-TTS(GPU bf16) + LLM 缩句播报 + 应答语音包
         sessions/   会话存储（索引+事件流）
DSH      @deepseek-ai/dsh：sdk（主会话）/ headless（子任务），
         OpenAI 兼容 provider 可配置（默认 zai glm-5.3-flash）
```

设置（`run/settings.json`，全部热生效）：provider API/模型、人设 SystemPrompt、
词表、声纹阈值、TTS 音色（自然语言描述）、权限、音乐服务……顶栏模型下拉支持自定义模型列表。

## 开发

```sh
make test              # 92 项单测（语音/语义/自进化/音乐/偏好）
cd web && npm run build  # 前端类型检查 + 构建
SPICA_LIVE=1 .venv/bin/python -m tools.e2e_smoke       # 全链路 E2E
SPICA_LIVE=1 .venv/bin/python -m tools.evolution_e2e   # 自进化 E2E
```

文档：[效果层规范](docs/design/effect-layer-spec.md)（视觉硬约束）· [动效参数](docs/design/motion-params.md) · [MusicFree 部署](docs/musicfree-setup.md) · [M1 验收清单](docs/acceptance-m1.md)
