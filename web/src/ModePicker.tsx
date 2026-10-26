import { useEffect, useRef, useState } from "react";
import { useSpica, send } from "./state";

const MODE_LIST = [
  { value: "minimal", label: "⚡ 极简", desc: "Token 省 60%+" },
  { value: "standard", label: "○ 常规", desc: "默认行为" },
  { value: "coding", label: "⌨ 编程", desc: "三阶段+强制测试" },
  { value: "custom", label: "🔧 定制", desc: "修改 SPICA 源码" },
];

/** 模式选择器（顶栏第一个控件）。 */
export default function ModePicker() {
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

  const value = current?.mode || "standard";
  const item = MODE_LIST.find(m => m.value === value);

  const pick = (v: string) => {
    setClosing(true);
    setTimeout(() => { setOpen(false); setClosing(false); }, 250);
    if (v !== value) {
      send({ t: "session_update", id: current?.id, patch: { mode: v } });
    }
  };

  return (
    <div className={`model-picker ${open ? "open" : ""}`} ref={ref}>
      <button className="model-current" onClick={() => setOpen(!open)}
        title="模式">
        {item?.label || "常规"}
        <span className={`turn-caret ${open ? "open" : ""}`}>▾</span>
      </button>
      {(open || closing) && (
        <div className="model-menu">
          {MODE_LIST.map(m => (
            <div key={m.value}
              className={`model-item ${value === m.value ? "active" : ""}`}
              onClick={() => pick(m.value)}>
              <span>{m.label}</span>
              <span className="model-sub">{m.desc}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
