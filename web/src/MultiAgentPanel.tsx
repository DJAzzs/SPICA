import { useState } from "react";
import { useSpica, send } from "./state";

const PRESETS = [
  { key: "investigation", label: "🔍 调查", desc: "搜索+汇总+审查",
    agents: ["搜索者", "汇总者", "审查者"] },
  { key: "code_review", label: "🧪 代码评审", desc: "编码+测试+审查",
    agents: ["编码者", "测试者", "审查者"] },
  { key: "analysis", label: "📊 分析", desc: "数据+分析+报告",
    agents: ["数据者", "分析者", "报告者"] },
  { key: "adversarial", label: "⚔️ 对抗", desc: "正方+反方+裁判",
    agents: ["正方", "反方", "裁判"] },
];

/** 多智能体配置面板 — 选择预设或自定义 Agent。 */
export default function MultiAgentPanel() {
  const current = useSpica((s) => s.currentSession);
  const [selected, setSelected] = useState("investigation");
  const [open, setOpen] = useState(false);
  const enabled = !!current?.multi_agent;

  if (!enabled) return null;

  const preset = PRESETS.find(p => p.key === selected);

  return (
    <div className="ma-panel-trigger">
      <button className="ma-trigger-btn" onClick={() => setOpen(!open)}
        title="多智能体配置">
        {preset?.label || "多智能体"}
        <span className="turn-caret">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="ma-panel">
          <div className="ma-title">选择预设方案</div>
          {PRESETS.map(p => (
            <div key={p.key}
              className={`ma-preset ${selected === p.key ? "on" : ""}`}
              onClick={() => setSelected(p.key)}>
              <span className="ma-preset-label">{p.label}</span>
              <span className="ma-preset-desc">{p.desc}</span>
              <span className="ma-preset-count">{p.agents.length} 个 Agent</span>
            </div>
          ))}

          <div className="ma-agents-preview">
            {preset?.agents.map((a, i) => (
              <div key={i} className="ma-agent-chip">
                <span className="ma-agent-num">{i + 1}</span>
                {a}
              </div>
            ))}
          </div>

          <button className="ma-launch" onClick={() => {
            send({ t: "session_update", id: current?.id,
              patch: { ma_preset: selected } });
            setOpen(false);
          }}>
            应用方案
          </button>

          <div className="ma-hint">
            任务发送后将自动使用此方案的多智能体并行执行
          </div>
        </div>
      )}
    </div>
  );
}
