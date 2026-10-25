import { useEffect, useRef, useState } from "react";
import { useSpica, send } from "./state";

/** 各模型支持的思考深度档位 */
const MODEL_EFFORTS: Record<string, string[]> = {
  "glm-5.3-flash": ["low", "medium", "high", "max"],
  "glm-5.3": ["low", "medium", "high", "max"],
  "glm-4.6": ["low", "medium", "high"],
};

const DEFAULT_EFFORTS = ["low", "medium", "high", "max"];

const EFFORT_LABELS: Record<string, string> = {
  "": "Default",
  "low": "Low",
  "medium": "Medium",
  "high": "High",
  "max": "Max",
};

/** 统一模型+思考深度选择器（单一下拉）。 */
export default function ModelPicker() {
  const settings = useSpica((s) => s.settings);
  const current = useSpica((s) => s.currentSession);
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const custom: string[] = (settings?.custom_models || "")
    .split(",").map((s: string) => s.trim()).filter(Boolean);
  const models = [...new Set(["glm-5.3-flash", "glm-5.3", "glm-4.6", ...custom])];
  const model = current?.model_override || "";
  const effort = current?.reasoning_effort_override || "";

  const efforts = model ? (MODEL_EFFORTS[model] || DEFAULT_EFFORTS) : [];
  const effortLabel = EFFORT_LABELS[effort] || "Default";
  const label = model
    ? `${model}${effort ? ` · ${effortLabel}` : ""}`
    : "Model: Auto";

  const closeMenu = () => {
    setClosing(true);
    setTimeout(() => { setOpen(false); setClosing(false); }, 250);
  };
  const pickModel = (m: string) => {
    closeMenu();
    if (m !== model) {
      send({ t: "session_update", id: current?.id,
        patch: { model_override: m } });
    }
  };

  const pickEffort = (e: string) => {
    closeMenu();
    send({ t: "session_update", id: current?.id,
      patch: { reasoning_effort_override: e } });
  };

  return (
    <div className={`model-picker ${open ? "open" : ""}`} ref={ref}>
      <button className="model-current" onClick={() => setOpen(!open)}
        title="Model & reasoning effort">
        {label}
        <span className={`turn-caret ${open ? "open" : ""}`}>▾</span>
      </button>

      {(open || closing) && (
        <div className="model-menu">
          {/* 模型列表 */}
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

          {/* 思考深度（选了模型才显示） */}
          {model && (
            <>
              <div className="model-sep" />
              <div className="model-section">Reasoning Effort</div>
              {["", ...efforts].map(e => (
                <div key={e || "default"}
                  className={`model-item ${effort === e ? "active" : ""}`}
                  onClick={() => pickEffort(e)}>
                  <span>{EFFORT_LABELS[e]}</span>
                  {effort === e && <span className="model-sub">✓</span>}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
