import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSpica, send } from "./state";
import { FolderIcon } from "./icons";
import DirBrowser from "./DirBrowser";

/** 相对时间 */
function relTime(ts: number): string {
  if (!ts) return "";
  const diff = (Date.now() / 1000 - ts);
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时`;
  if (diff < 2592000) return `${Math.floor(diff / 86400)}天`;
  return `${Math.floor(diff / 2592000)}个月`;
}

const MIN_W = 200, MAX_W = 420, DEFAULT_W = 280;

/** 侧边栏：按工作区分组，可拖拽调宽。 */
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
  const [browsing, setBrowsing] = useState(false);
  const [width, setWidth] = useState(() =>
    parseInt(localStorage.getItem("spica-side-w") || String(DEFAULT_W)));

  // 同步宽度到 CSS 变量（side-tab 按钮跟随）
  useEffect(() => {
    document.documentElement.style.setProperty("--side-w", `${width + 12}px`);
  }, [width, open]);
  const dragRef = useRef(false);
  const sidebarRef = useRef<HTMLDivElement>(null);

  // 拖拽调宽
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragRef.current) return;
      const w = Math.max(MIN_W, Math.min(MAX_W, e.clientX));
      setWidth(w);
    };
    const onUp = () => {
      if (dragRef.current) {
        dragRef.current = false;
        localStorage.setItem("spica-side-w", String(width));
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [width]);

  const startDrag = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

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
  const createSession = () => {
    send({ t: "session_new" });
    setCreating(false); setNewCwd("");
  };

  return (
    <div ref={sidebarRef}
      className={`sidebar-inline ${open ? "open" : ""}`}
      style={{ width }}>
      {/* 拖拽手柄 */}
      <div className="side-drag" onMouseDown={startDrag} />

      {/* 顶行：标题 + 关闭 */}
      <div className="side-top">
        <svg width="28" height="28" viewBox="0 0 64 64" style={{ flex: "none" }}>
          <path d="M32 6 C42 18 46 26 46 32 C46 38 42 46 32 58 C22 46 18 38 18 32 C18 26 22 18 32 6 Z"
            fill="none" stroke="var(--mist)" strokeWidth="3" strokeLinejoin="round"/>
          <path d="M32 14 C38 22 41 27 41 32 C41 37 38 42 32 50 C26 42 23 37 23 32 C23 27 26 22 32 14 Z"
            fill="var(--sand)" opacity="0.85"/>
        </svg>
        <span className="side-top-label">SPICA</span>
      </div>

      {/* 新会话 */}
      <button className="side-new-btn" onClick={() =>
        window.dispatchEvent(new Event("spica-new-session"))}>
        ＋ 新会话
      </button>

      <div className="side-ws-header">
        <span className="side-ws-label">工作区</span>
        <div className="side-ws-actions">
          <button className="side-icon-btn" title="搜索"
            onClick={() => setSearchOpen(!searchOpen)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
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

      {/* 可滚动的会话列表 */}
      <div className="side-scroll">
        <div className="side-groups">
          {filtered.map(g => (
            <div key={g.cwd} className="side-group">
              <div className="side-group-head-row">
                <button className="side-group-head"
                  onClick={() => setCollapsed({ ...collapsed,
                    [g.cwd]: !collapsed[g.cwd] })}>
                  <span className={`turn-caret ${collapsed[g.cwd] ? "" : "open"}`}>▸</span>
                  <FolderIcon size={14} />
                  <span className="side-group-name" title={g.cwd}>{g.name}</span>
                  <span className="side-group-count">{g.sessions.length}</span>
                </button>
                <button className="side-group-del" title="删除全部"
                  onClick={() => setConfirmDel(`ws:${g.cwd}`)}>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <path d="M3 6h18M8 6V4h8v2M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                  </svg>
                </button>
              </div>

              {confirmDel === `ws:${g.cwd}` && (
                <div className="side-confirm">
                  <span>删除 {g.sessions.length} 个会话？</span>
                  <button className="side-confirm-yes" onClick={() => {
                    setConfirmDel(null);
                    g.sessions.forEach((s: any) => send({ t: "session_delete", id: s.id }));
                  }}>删除</button>
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
                      {confirmDel === s.id && (
                        <div className="side-confirm" onClick={e => e.stopPropagation()}>
                          <span>删除？</span>
                          <button className="side-confirm-yes"
                            onClick={() => deleteSession(s.id)}>是</button>
                          <button className="side-confirm-no"
                            onClick={() => setConfirmDel(null)}>否</button>
                        </div>
                      )}
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
    </div>
  );
}
