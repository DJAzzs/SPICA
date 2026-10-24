import { useSpica, send } from "./state";

const PERM_LABEL: Record<string, string> = {
  "read-only": "只读",
  "workspace-write": "工作区写入",
  "danger-full-access": "完全访问",
};
const PERM_ORDER = ["read-only", "workspace-write", "danger-full-access"];

function fmtTime(ts: number) {
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 会话管理：列表 / 打开 / 新建 / 重命名 / 工作区 / 权限 / 删除。 */
export default function Sessions() {
  const sessions = useSpica((s) => s.sessions);
  const current = useSpica((s) => s.currentSession);

  const rename = (s: any) => {
    const t = prompt("会话标题", s.title || "");
    if (t !== null && t.trim()) send({ t: "session_update", id: s.id, patch: { title: t.trim() } });
  };
  const setcwd = (s: any) => {
    const c = prompt("工作区目录（绝对路径）", s.cwd || "");
    if (c !== null && c.trim()) send({ t: "session_update", id: s.id, patch: { cwd: c.trim() } });
  };
  const cyclePerm = (s: any) => {
    const next = PERM_ORDER[(PERM_ORDER.indexOf(s.perm) + 1) % PERM_ORDER.length];
    send({ t: "session_update", id: s.id, patch: { perm: next } });
  };
  const del = (s: any) => {
    if (confirm(`删除会话「${s.title || s.id}」？（本地记录移除；不影响已存档内容）`)) {
      send({ t: "session_delete", id: s.id });
    }
  };

  return (
    <div className="panel">
      <div className="inner" style={{ width: 720 }}>
        <h1>会话</h1>
        <div className="btn-row" style={{ marginBottom: 24 }}>
          <button className="btn primary" onClick={() => send({ t: "session_new" })}>
            ＋ 新会话
          </button>
        </div>

        {(sessions || []).length === 0 && (
          <div className="hint">还没有会话——发第一个任务会自动创建并起名。</div>
        )}

        {(sessions || []).map((s: any) => (
          <div key={s.id} className={`sess-row ${current?.id === s.id ? "on" : ""}`}>
            <div className="sess-main" onClick={() => send({ t: "session_open", id: s.id })}>
              <div className="sess-title">
                {s.title || "未命名"}
                {current?.id === s.id && <span className="sess-cur">当前</span>}
              </div>
              <div className="sess-meta">
                {fmtTime(s.updated)} · {s.model || "—"} · {s.cwd}
                {s.dsh_session_id ? ` · ${s.dsh_session_id.slice(0, 10)}…` : ""}
              </div>
            </div>
            <div className="sess-actions">
              <button className="btn" onClick={() => cyclePerm(s)}
                title="点击切换权限（重启任务进程后生效）">
                {PERM_LABEL[s.perm] || s.perm}
              </button>
              <button className="btn" onClick={() => setcwd(s)}>工作区</button>
              <button className="btn" onClick={() => rename(s)}>重命名</button>
              <button className="btn" onClick={() => del(s)}>删除</button>
            </div>
          </div>
        ))}

        <div className="hint" style={{ marginTop: 24 }}>
          权限说明：只读 = Agent 仅能读文件；工作区写入 = 默认（会话目录内可写，敏感操作询问）；
          完全访问 = 免审批全盘可写（谨慎）。工作区/权限修改对下一个任务生效。
        </div>
        <div className="btn-row"><a className="btn" href="#/">返回</a></div>
      </div>
    </div>
  );
}
