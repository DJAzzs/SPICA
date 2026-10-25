import { useEffect, useRef, useState } from "react";
import { useSpica, send } from "./state";

const PERMS = [
  { value: "read-only", label: "只读", desc: "仅查看，不修改" },
  { value: "workspace-write", label: "工作区写入", desc: "可修改工作区文件" },
  { value: "danger-full-access", label: "完全访问", desc: "无限制（危险）" },
];

/** 会话权限选择器（顶栏，随时切换）。 */
export default function PermPicker() {
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

  const value = current?.perm || "workspace-write";
  const item = PERMS.find(p => p.value === value);

  const pick = (v: string) => {
    setClosing(true);
    setTimeout(() => { setOpen(false); setClosing(false); }, 250);
    if (v !== value) {
      send({ t: "session_update", id: current?.id, patch: { perm: v } });
    }
  };

  return (
    <div className={`model-picker ${open ? "open" : ""}`} ref={ref}>
      <button className="model-current perm" onClick={() => setOpen(!open)}
        title="会话权限">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          {value === "danger-full-access"
            ? <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></>
            : value === "read-only"
            ? <><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></>
            : <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="M9 12l2 2 4-4" /></>}
        </svg>
        {item?.label}
        <span className={`turn-caret ${open ? "open" : ""}`}>▾</span>
      </button>
      {(open || closing) && (
        <div className="model-menu">
          {PERMS.map(p => (
            <div key={p.value}
              className={`model-item ${value === p.value ? "active" : ""}`}
              onClick={() => pick(p.value)}>
              <span>{p.label}</span>
              <span className="model-sub">{p.desc}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
