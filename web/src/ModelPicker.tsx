import { useEffect, useRef, useState } from "react";
import { useSpica, send } from "./state";

/** 各模型支持的 effort 档位 */
const EFFORT_MAP: Record<string, string[]> = {
  "glm": ["auto", "low", "medium", "high", "max"],
  "grok": ["auto", "low", "medium", "high", "xhigh"],
  "gpt": ["auto", "low", "medium", "high"],
  "claude": ["auto", "low", "medium", "high"],
  "default": ["auto", "low", "medium", "high", "max"],
};

/** effort 显示名 */
function effortLabel(v: string): string {
  if (v === "xhigh") return "xHigh";
  return v.charAt(0).toUpperCase() + v.slice(1);
}

/** 按模型名取档位列表 */
function effortsFor(model: string): string[] {
  for (const prefix in EFFORT_MAP) {
    if (model.toLowerCase().startsWith(prefix)) return EFFORT_MAP[prefix];
  }
  return EFFORT_MAP.default;
}

/** 按钮显示文本 */
function displayLabel(model: string, effort: string): string {
  const mAuto = !model;
  const eAuto = !effort || effort === "auto";
  if (mAuto && eAuto) return "AUTO";
  if (mAuto) return `Auto ${effortLabel(effort)}`;
  if (eAuto) return `${model} Auto`;
  return `${model} ${effortLabel(effort)}`;
}

/** 统一模型+effort 选择器（下拉 + 内嵌滑块）。 */
export default function ModelPicker() {
  const settings = useSpica((s) => s.settings);
  const current = useSpica((s) => s.currentSession);
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) {
        setClosing(true);
        setTimeout(() => { setOpen(false); setClosing(false); }, 250);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const custom: string[] = (settings?.custom_models || "")
    .split(",").map((s: string) => s.trim()).filter(Boolean);
  const models = [...new Set(["glm-5.3-flash", "glm-5.3", "glm-4.6", ...custom])];

  const model = current?.model_override || "";
  const effort = current?.reasoning_effort_override || "";
  const efforts = effortsFor(model || "glm");
  const effortIdx = Math.max(0, efforts.indexOf(effort || "auto"));

  const label = displayLabel(model, effort || "auto");

  const pickModel = (m: string) => {
    if (m !== model) {
      send({ t: "session_update", id: current?.id,
        patch: { model_override: m } });
    }
  };

  const pickEffort = (e: string) => {
    send({ t: "session_update", id: current?.id,
      patch: { reasoning_effort_override: e } });
  };

  return (
    <div className={`model-picker ${open ? "open" : ""}`} ref={ref}>
      <button className="model-current" onClick={() => setOpen(!open)}
        title="模型 & Reasoning Effort">
        {label}
        <span className={`turn-caret ${open ? "open" : ""}`}>▾</span>
      </button>

      {open && (
        <div className="model-menu">
          <div className={`model-item ${!model ? "active" : ""}`}
            onClick={() => pickModel("")}>
            <span>Auto</span>
            <span className="model-sub">by difficulty</span>
          </div>
          <div className="model-sep" />
          {models.map(m => (
            <div key={m}
              className={`model-item ${model === m ? "active" : ""}`}
              onClick={() => pickModel(m)}>
              <span>{m}</span>
              {model === m && <span className="model-sub">✓</span>}
            </div>
          ))}

          {/* Effort 滑块 */}
          <div className="model-sep" />
          <div className="model-section">Reasoning Effort</div>
          <div className="effort-slider">
            <input
              type="range"
              min={0}
              max={efforts.length - 1}
              step={1}
              value={effortIdx}
              onChange={(e) => pickEffort(efforts[parseInt(e.target.value)])}
            />
            <span className="effort-value">{effortLabel(efforts[effortIdx] || "auto")}</span>
          </div>
        </div>
      )}
    </div>
  );
}
