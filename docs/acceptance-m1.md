# M1 语音主循环 · 验收清单

> 自动化部分已于 2026-10-24 全部通过（38 单测 + E2E 真链路）。
> 本清单剩余项需在**桌面会话**（GPU/麦克风/浏览器真实环境）人工验收。

## 已自动验证 ✅

| 项 | 证据 |
|---|---|
| 唤醒/结束词匹配（中英+变体+同音） | tests/test_wake.py 15 用例 |
| VAD 分段 / 流式 partials / SenseVoice 终稿 / 声纹嵌入 | tests/test_voice.py |
| 管线状态机（唤醒兜底/迟到回收/TTS 门控/followup 超时） | tests/test_voice.py |
| 两段式改写 + 难度路由 + reasoningEffort 映射 | tests/test_llm.py（含 zai 真实冒烟） |
| 语义机（唤醒→执行→完成/插话队列/暂停恢复/结束词确认/关停存档） | tests/test_semantics.py |
| DSH headless + sdk 真实冒烟（zai glm-5.3，事件流完整） | tools/sdk_smoke.py |
| TTS：GPU bf16 加载 1.3s，thinking-disabled 快速合成，14 条应答包预生成 | run/server.log |
| **E2E 真链路**：语音→唤醒→改写→路由→DSH 执行 ls→回答→task_done | tools/e2e_smoke.py PASS |

## 桌面人工验收（待用户操作）

```sh
cd /home/dja/桌面/SPICA && make up
# 浏览器打开 http://127.0.0.1:8666 （Firefox）
```

1. **硬件诊断页**（#/diagnose）：能看到 WL24A 麦克风、点"开始采集"后主界面声纹线随说话起伏；摄像头"探测"报告有无。
2. **首启向导**（#/wizard）：唤醒词模拟匹配命中；声纹注册（说 3 句话）后他人声音/TTS 回放喊"Hey, SPICA"应被拒（静默）。
3. **唤醒**：说 "Hey, SPICA" 或 "嘿SPICA" <600ms 听到应答（GPU 首包应远低于此）；画面角点圆点灰转暖呼吸 1.2s。
4. **任务**：唤醒后说 15s 任务（如"帮我在 workspace 里建一个 TODO.md，写入三条待办"）——边说边见声纹线/进度线；说完 ≤2s 听到"收到，开始…"；执行中每步一句播报（GPU 首音频 <1.5s）；结束总结+呼叫。
5. **暂停/恢复**：执行中说"暂停"→TTS 停+确认语；说"继续"→同一 DSH 会话接续。
6. **插话**：执行中说新指令→"记下了，当前任务完成后就做"→上一任务 turn_end 后自动执行。
7. **结束词**：说 "Bye, SPICA" 或 "拜拜SPICA"→（执行中会先问确认，再说"确定"）→告别语音→浏览器告别画面→`ps` 无残留→`make killall` 幂等→`archives/` 有存档、workspace 有 git commit。
8. **效果层四态**（按 docs/design/motion-params.md §13）：遮字可辨听/做/完；无声可辨四态；静置 10s 仍有呼吸；30s 录屏无弹跳爆炸；截图主体 <40% 唯一强调色。

## 已知限制（M2 前修复/观察）

- 流式 partial 的英文全大写（引擎特性，匹配已归一化无碍；审阅模式显示原样）。
- 迟到唤醒回收的 final 可能取流式文本（错字率略高）；正常实时流下 SenseVoice 终稿为主。
- 向导"试听"走 /api/settings POST（简版）；音色描述自定义未持久化校验。
- 浏览器端（AudioWorklet/Three.js 场景/向导交互）尚未经真实桌面浏览器点击验证——首次验收若发现 UI 问题按效果层规范返工。
