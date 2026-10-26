# SPICA

**语音优先的本地 Agent 操控台** —— 像贾维斯一样对话：唤醒词 + 声纹门控 + 流式识别 + AI 提示词改写 + DSH 底座执行 + 本地 Qwen3-TTS 逐步播报 + 自动配乐 + 智能闪避。目标：不动键盘鼠标完成一次 Agent 任务，而且它**越用越懂你**（记忆 / 技能 / 音乐偏好 / 身份认知持续自进化）。

```
你："Hey, SPICA，帮我在工作区建一个爬虫项目骨架"
SPICA："收到，开始。" →（每步一句播报，音乐自动压低）→ 文件变更卡片 →"已完成，用时 1 分 23 秒"
你："Bye, SPICA" → 存档 → 告别语音 → 全部进程优雅退出
```

## 功能全景

### 🎙 语音交互
- 唤醒/结束词：内置 "Hey, SPICA" / "嘿SPICA" / "Bye, SPICA" / "拜拜SPICA"（可自定义 + 混淆变体表）
- 声纹门控：只回应注册者，他人静默；注册全程零 TTS（防自采）
- 双引擎 ASR：流式 Zipformer（中英）实时转写 + SenseVoice 整段精修；边说边改写（两段式：预热草稿 + 最小校正）
- 自回声免疫：播报期整段丢弃 + 回声文本匹配双保险
- 手动聆听按钮（🎤），再点取消
- 闲聊分流："你是谁"直接身份回复（不走 DSH），任务才进完整管线

### 🤖 Agent 能力（DSH 底座）
- 难度路由：cheap LLM 分级 simple/normal/complex → 自动选模型与推理强度（reasoningEffort）
- **手动模型 + 思考深度选择器**：顶栏双下拉（模型 + 5 档思考深度），会话级持久
- 思考模型支持：灰色"思考中"实时滚动可折叠；任务完成自动收起过程，只留总结
- 文件变更摘要卡：按变更行数排序，绿 +x / 红 -y，便利贴（浅色）/ 液态玻璃（深色）
- 运行统计底栏：模型、tok/s、上下文占用 %（迷你进度条，>60% 变黄 >80% 变红）、轮/步、总 tokens；hover 浮出详情卡
- 插话队列、语音/按钮暂停恢复（SIGTERM + 持久化会话 resume）
- **权限升级卡**：Agent 被拒 → 人话解释（类型 + LLM 通俗说明 + 可折叠技术细节）→ 同意一次 / 永远同意 / 拒绝（按钮 + 语音）
- **时间感知**：每个 prompt 自动注入年月日/星期/时段，Agent 知道现在是深夜还是早晨

### 🧠 自进化（Hermes 式，全自动 + 可审计）
- 有界记忆：MEMORY/USER 双文件（2200/1375 字符强制蒸馏），安全扫描，每 5 轮自动 nudge
- 技能收获：≥5 工具调用成功后自动提炼 SKILL 入库，渐进披露注入
- **身份认知**：内置 System Prompt（含动态驱动模型 + 时间），三层模型（内置只读 + 人设追加 + 高级覆盖）
- 全部自动写入记录在 `run/evolution-audit.jsonl`

### 🗂 会话系统
- 按工作区分组的侧边栏会话树（内嵌布局，挤占内容区非覆盖）
- 自动命名、本地持久化、服务重启自动续接
- 每会话独立工作区与权限（只读/工作区写入/完全访问）
- 导出 zip、`/compact` 上下文压缩、新会话创建表单（选工作区 + 权限）

### 🎵 音乐系统（MusicFree / OpenSubsonic）
- "放一首周杰伦的晴天"→ 远程搜索 → 自动下载入库 → 播放（黑胶唱片旋转封面）
- **TTS 智能闪避**：SPICA 说话/你说话，音乐 1 秒渐弱，结束 1 秒渐回
- 描述选歌："来首英文摇滚"（LLM 翻译具体歌名兜底）
- 偏好学习：70% 喜好（count^0.7 加权）+ 30% 探索
- 任务自动配乐（可选）：flash 按任务气质选歌



### 🎛 v2 新增：控制面板与模式系统
- **四种模式**：⚡极简（Token 省 60%+）/ ○常规 / ⌨编程（三阶段流水线） / 🔧定制（修改 SPICA 自身）
- **缜密模式**：L0 程序化检查 + L1 语义一致性 + L2 对抗审查 + L3 交叉验证（按复杂度自动升级）
- **多智能体**：4 套预设（调查/代码评审/分析/对抗），并行 Agent 执行 + 结果合成
- **effort 滑块**：模型推理深度可视化调节（Auto—Low—Medium—High—Max/xHigh）
- **任务耗时预估**：基于历史统计，任务开始前显示"⏱ 预计 ~2 分钟"

### 📊 v2 新增：体验层
- **网页浏览折叠卡**：Agent 浏览网页时显示可折叠预览
- **后台任务指示器**：左上角 ⚙ N 实时显示
- **音乐播放历史**：🎵 查看/删除/清空（同步偏好）
- **会话重命名**：侧边栏 ✎ 按钮
- **验证徽章**：缜密模式下任务完成后显示 ✓/⚠/✗ + 详情

### ⌨️ 对话式 UI
- DSH 式对话流（Markdown 渲染 + **代码块点击复制**）
- **用户消息右对齐** + 时间戳，Agent 左对齐 + 完成时间戳
- 🎤 手动聆听 + ＋ 上传（chips 可删，任务自动附带文件提示）
- **斜杠命令面板**：输入 `/` 弹出，↑↓/Tab/点击选择
- **右侧导航轨**：每个指令节点，点击跳转，滚动联动高亮
- 双主题：米白新拟物（穿孔导航 + 便利贴变更卡 + 网格线底）/ 钛黑液态玻璃（光晕 + 毛玻璃刻度）

## 快速开始

```sh
make deps        # .venv（Python 3.12）+ 清华源装依赖
make models      # 下载 sherpa-onnx 四模型（hf-mirror）
make check       # 环境自检
make up          # 后台启动 → http://127.0.0.1:8666
make log         # 跟日志    make stop / status / killall
```

首次使用：页面点击授权麦克风 → 向导（声纹/唤醒词/音色）→ 说 "Hey, SPICA"。

**音乐**（可选）：部署 [MusicFree](docs/musicfree-setup.md)（Docker 一行）→ 装一个 RemoteSearch 插件 → 设置页填地址。

## 命令与语音

| 键盘命令 | 语音说法 | 作用 |
|---|---|---|
| `/plan <目标>` | "只做计划…" | 只读规划（单轮） |
| `/compact` | "压缩一下上下文" | 压缩续命 |
| `/export` | "导出当前会话" | zip 下载 |
| `/goal <目标>` | "制定目标…" | 长期目标多轮推进 |
| `/music <词/stop/taste>` | "放一首…" | 音乐播放与偏好 |
| `/memory add/list/remove` | "记住 xxx" | 记忆管理 |
| `/skills list/del` | — | 技能库管理 |
| — | "暂停 / 继续" | 任务控制 |
| — | "同意 / 永远同意 / 拒绝" | 权限升级应答 |

## 架构

```
web/     React + TS（Vite）
         对话流 + Markdown + 思考折叠 + 计时 + 文件变更卡
         AudioWorklet 采集（AEC + 分数重采样）
         WebAudio TTS 播放 + 音乐卡 ducking
         双主题（新拟物 / 液态玻璃）+ Three.js 光晕
         侧边栏（工作区分组会话树）+ 导航轨 + 统计栏
server/  Python FastAPI（127.0.0.1:8666）
         voice/      silero-VAD → 唤醒匹配 → 声纹 → 双 ASR
         agent/      sdk_client / 两段式改写 / 难度路由 / 语义状态机
                     闲聊分流 / 权限升级 / 时间感知 / 身份注入
         evolution/  有界记忆 + 技能收获 + 审计
         media/      MusicFree + 偏好学习
         tts/        Qwen3-TTS + LLM 缩句 + 应答语音包
         sessions/   会话存储（索引 + 事件流）
DSH      @deepseek-ai/dsh：sdk（主会话）/ headless（子任务）
         OpenAI 兼容 provider 可配置（默认 zai glm-5.3-flash）
```

设置（`run/settings.json`，全部热生效）：provider API / 模型 / 人设 / 身份覆盖 / 词表 / 声纹阈值 / TTS 音色 / 权限 / 音乐服务。

## 开发

```sh
make test                # 104 项单测
cd web && npm run build  # 前端构建
SPICA_LIVE=1 .venv/bin/python -m tools.e2e_smoke       # 全链路 E2E
SPICA_LIVE=1 .venv/bin/python -m tools.evolution_e2e   # 自进化 E2E
```

文档：[效果层规范](docs/design/effect-layer-spec.md) · [动效参数](docs/design/motion-params.md) · [MusicFree 部署](docs/musicfree-setup.md) · [M1 验收清单](docs/acceptance-m1.md)
