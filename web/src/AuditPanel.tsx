import { useSpica } from "./state";

/** 审计栏 — 右侧滑出，显示完整活动时间线。 */
export default function AuditPanel() {
  const msgs = useSpica((s) => s.msgs);
  const [open] = [false]; // 由 App 控制

  if (!open) return null;

  return (
    <div className="audit-panel">
      <div className="audit-title">📋 活动记录</div>
      <div className="audit-list">
        {msgs.slice(-50).reverse().map((m, i) => (
          <div key={i} className={`audit-item ${m.role}`}>
            <span className="audit-role">{m.role}</span>
            <span className="audit-text">{m.text?.slice(0, 80)}</span>
            <span className="audit-time">
              {m.ts ? new Date(m.ts * 1000).toLocaleTimeString("zh-CN",
                { hour: "2-digit", minute: "2-digit", hour12: false }) : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
