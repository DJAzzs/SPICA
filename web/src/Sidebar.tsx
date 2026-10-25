import { useMemo, useState } from "react";
import { useSpica, send } from "./state";
import { FolderIcon } from "./icons";

/** 相对时间：x分钟/x小时/x天/x月 */
function relTime(ts: number): string {
  if (!ts) return "";
  const diff = (Date.now() / 1000 - ts);
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时`;
  if (diff < 2592000) return `${Math.floor(diff / 86400)}天`;
  return `${Math.floor(diff / 2592000)}个月`;
}

/** 侧边栏：按工作区分组的会话树（内嵌布局），支持删除 + 相对时间。 */
export default function Sidebar({ open }: { open: boolean }) {
  const sessions = useSpica((s) => s.sessions);
  const current = useSpica((s) => s.currentSession);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newCwd, setNewCwd] = useState("");
  const [newPerm, setNewPerm] = useState("workspace-write");
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  const groups = useMemo(() => {
    const map = new Map<string, any[]>();
    (sessions || []).forEach((s: any) => {
      const cwd = s.cwd || "默认";
      if (!map.has(cwd)) map.set(cwd, []);
      map.get(cwd)!.push(s);
    });
    return [...map.entries()].map(([cwd, ss]) => ({
      cwd, name: cwd.split("/").pop() || cwd, sessions: ss,
    })).sort((a, b) =>
      a.cwd === current?.cwd ? -1 : b.cwd === current?.cwd ? 1 : 0);
  }, [sessions, current]);

  const filtered = search.trim()
    ? groups.map(g => ({ ...g,
        sessions: g.sessions.filter((s: any) =>
          (s.title || "").toLowerCase().includes(search.toLowerCase())),
      })).filter(g => g.sessions.length > 0)
    : groups;

  const openSession = (id: string) => send({ t: "session_open", id });
  const deleteSession = (id: string) => {
    setConfirmDel(null);
    send({ t: "session_delete", id });
  };
  const deleteWorkspace = (cwd: string, ids: string[]) => {
    setConfirmDel(null);
    ids.forEach(id => send({ t: "session_delete", id }));
  };

  const createSession = () => {
    send({ t: "session_new" });
    setCreating(false); setNewCwd("");
  };

  if (!open) return null;

  return (
    <div className="sidebar-inline">
      <button className="side-new-btn" onClick={() => setCreating(!creating)}>
        ＋ 新会话
      </button>
      {creating && (
        <div className="side-create">
          <input type="text" placeholder="工作区路径（默认 workspace）"
            value={newCwd} onChange={e => setNewCwd(e.target.value)} />
          <select value={newPerm} onChange={e => setNewPerm(e.target.value)}>
            <option value="read-only">只读</option>
            <option value="workspace-write">工作区写入</option>
            <option value="danger-full-access">完全访问</option>
          </select>
          <button className="side-create-btn" onClick={createSession}>创建</button>
        </div>
      )}
      <div className="side-ws-header">
        <span className="side-ws-label">工作区</span>
        <div className="side-ws-actions">
          <button className="side-icon-btn" title="搜索"
            onClick={() => setSearchOpen(!searchOpen)}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
            </svg>
          </button>
        </div>
      </div>
      {searchOpen && (
        <input type="text" className="side-search" placeholder="搜会话…"
          value={search} onChange={e => setSearch(e.target.value)} autoFocus />
      )}
      <div className="side-groups">
        {filtered.map(g => (
          <div key={g.cwd} className="side-group">
            <div className="side-group-head-row">
              <button className="side-group-head"
                onClick={() => setCollapsed({ ...collapsed,
                  [g.cwd]: !collapsed[g.cwd] })}>
                <span className={`turn-caret ${collapsed[g.cwd] ? "" : "open"}`}>▸</span>
                <FolderIcon size={12} />
                <span className="side-group-name" title={g.cwd}>{g.name}</span>
                <span className="side-group-count">{g.sessions.length}</span>
              </button>
              <button className="side-group-del" title="删除此工作区全部会话"
                onClick={() => setConfirmDel(`ws:${g.cwd}`)}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M3 6h18M8 6V4h8v2M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                </svg>
              </button>
            </div>

            {/* 确认删除工作区 */}
            {confirmDel === `ws:${g.cwd}` && (
              <div className="side-confirm">
                <span>删除 {g.sessions.length} 个会话？</span>
                <button className="side-confirm-yes" onClick={() =>
                  deleteWorkspace(g.cwd, g.sessions.map((s: any) => s.id))}>删除</button>
                <button className="side-confirm-no" onClick={() => setConfirmDel(null)}>取消</button>
              </div>
            )}

            {!collapsed[g.cwd] && (
              <div className="side-group-items">
                {g.sessions.map((s: any) => (
                  <div key={s.id}
                    className={`side-item ${current?.id === s.id ? "on" : ""}`}
                    onClick={() => openSession(s.id)}>
                    <span className="side-item-title">{s.title || "未命名"}</span>
                    <span className="side-item-meta">
                      <span className="side-item-time">{relTime(s.updated)}</span>
                      {s.source === "dsh" && <em>DSH</em>}
                    </span>
                    <button className="side-item-del"
                      onClick={(e) => { e.stopPropagation(); setConfirmDel(s.id); }}>
                      ✕
                    </button>
                  </div>
                ))}
                {/* 确认删除会话 */}
                {g.sessions.map((s: any) => confirmDel === s.id && (
                  <div key={`c-${s.id}`} className="side-confirm">
                    <span>删除「{(s.title || "未命名").slice(0, 14)}」？</span>
                    <button className="side-confirm-yes" onClick={() => deleteSession(s.id)}>删除</button>
                    <button className="side-confirm-no" onClick={() => setConfirmDel(null)}>取消</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {!filtered.length && (
          <div className="side-empty">{search ? "无匹配" : "暂无会话"}</div>
        )}
      </div>
    </div>
  );
}
