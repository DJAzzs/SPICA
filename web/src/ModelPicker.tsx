import { useEffect, useRef, useState } from "react";
import { useSpica, send } from "./state";

/** 自绘模型下拉（原生 select 的弹层不吃主题，深色下白得刺眼）。 */
export default function ModelPicker() {
  const settings = useSpica((s) => s.settings);
  const current = useSpica((s) => s.currentSession);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (open && !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const custom: string[] = (settings?.custom_models || "")
    .split(",").map((s: string) => s.trim()).filter(Boolean);
  const models = [...new Set(["glm-5.3-flash", "glm-5.3", "glm-4.6", ...custom])];
  const value = current?.model_override || "";
  const label = value || "模型：自动";

  const pick = (m: string) => {
    setOpen(false);
    if (m !== value) {
      send({ t: "session_update", id: current?.id,
        patch: { model_override: m } });
    }
  };

  return (
    <div className="model-picker" ref={ref}>
      <button className="model-current" onClick={() => setOpen(!open)}
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
  );
}
