import { useEffect, useRef, useState } from "react";
import { useSpica, send } from "./state";

const EFFORTS = [
  { value: "", label: "思考：默认" },
  { value: "low", label: "思考：低" },
  { value: "medium", label: "思考：中" },
  { value: "high", label: "思考：高" },
  { value: "max", label: "思考：最高" },
];

/** 自绘模型 + 思考深度下拉（手动选模型时出现深度选择）。 */
export default function ModelPicker() {
  const settings = useSpica((s) => s.settings);
  const current = useSpica((s) => s.currentSession);
  const [open, setOpen] = useState(false);
  const [effortOpen, setEffortOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const effortRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (open && !ref.current?.contains(e.target as Node)) setOpen(false);
      if (effortOpen && !effortRef.current?.contains(e.target as Node))
        setEffortOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open, effortOpen]);

  const custom: string[] = (settings?.custom_models || "")
    .split(",").map((s: string) => s.trim()).filter(Boolean);
  const models = [...new Set(["glm-5.3-flash", "glm-5.3", "glm-4.6", ...custom])];
  const value = current?.model_override || "";
  const label = value || "模型：自动";
  const effort = current?.reasoning_effort_override || "";
  const effortLabel = EFFORTS.find(e => e.value === effort)?.label || "思考：默认";

  const pick = (m: string) => {
    setOpen(false);
    if (m !== value) {
      send({ t: "session_update", id: current?.id,
        patch: { model_override: m } });
    }
  };

  const pickEffort = (e: string) => {
    setEffortOpen(false);
    send({ t: "session_update", id: current?.id,
      patch: { reasoning_effort_override: e } });
  };

  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
      <div className="model-picker" ref={ref}>
        <button className="model-current" onClick={() => { setOpen(!open); setEffortOpen(false); }}
          title="会话模型（自动=按难度路由）">
          {label}
          <span className={`turn-caret ${open ? "open" : ""}`}>▾</span>
        </button>
        {open && (
          <div className="model-menu">
            <div className={`model-item ${value === "" ? "active" : ""}`}
              onClick={() => pick("")}>
              自动<span className="model-sub">按难度路由</span>
            </div>
            {models.map((m) => (
              <div key={m} className={`model-item ${value === m ? "active" : ""}`}
                onClick={() => pick(m)}>
                {m}
                {value === m && <span className="model-sub">当前</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      {value && (
        <div className="model-picker" ref={effortRef}>
          <button className="model-current effort" onClick={() => { setEffortOpen(!effortOpen); setOpen(false); }}
            title="思考深度（兼容各模型的推理强度档位）">
            {effortLabel}
            <span className={`turn-caret ${effortOpen ? "open" : ""}`}>▾</span>
          </button>
          {effortOpen && (
            <div className="model-menu">
              {EFFORTS.map(e => (
                <div key={e.value} className={`model-item ${effort === e.value ? "active" : ""}`}
                  onClick={() => pickEffort(e.value)}>
                  {e.label}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
