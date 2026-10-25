import { useEffect, useState } from "react";
import { useSpica, send } from "./state";
import { FolderIcon, FileIcon } from "./icons";

/** 侧边栏：会话列表 + 工作区文件树。
 *  由左上角按钮触发，从左侧滑入。 */
export default function Sidebar({ open, onClose }: {
  open: boolean; onClose: () => void;
}) {
  const sessions = useSpica((s) => s.sessions);
  const current = useSpica((s) => s.currentSession);
  const [tree, setTree] = useState<{ dir: boolean; name: string }[]>([]);
  const [sessOpen, setSessOpen] = useState(false);
  const [treePath, setTreePath] = useState("");
  const [loadingTree, setLoadingTree] = useState(false);

  // 加载文件树根目录
  useEffect(() => {
    if (open && !tree.length && !loadingTree) {
      loadDir("");
    }
  }, [open]);

  const loadDir = async (sub: string) => {
    setLoadingTree(true);
    try {
      const r = await fetch(`/api/files/list?sub=${encodeURIComponent(sub)}`);
      const j = await r.json();
      if (!j.error) { setTree(j.entries || []); setTreePath(sub); }
    } catch { /* silent */ }
    setLoadingTree(false);
  };

  const openSession = (id: string) => {
    send({ t: "session_open", id });
  };

  return (
    <>
      {open && <div className="sidebar-mask" onClick={onClose} />}
      <div className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-head">
          <span className="sidebar-title">会话 & 工作区</span>
          <button className="sidebar-close" onClick={onClose}>✕</button>
        </div>

        {/* 会话列表 */}
        <div className="sidebar-section">
          <button className="sidebar-toggle" onClick={() => setSessOpen(!sessOpen)}>
            <span className="sidebar-label">会话（{sessions?.length || 0}）</span>
            <span className="turn-caret" style={{
              transform: sessOpen ? "rotate(90deg)" : "rotate(0)" }}>▸</span>
          </button>
          {sessOpen && (
            <>
              <button className="sidebar-new" onClick={() => {
                send({ t: "session_new" });
              }}>＋ 新会话</button>
              <div className="sidebar-sessions">
            {(sessions || []).slice(0, 12).map((s: any) => (
              <div key={s.id}
                className={`side-sess ${current?.id === s.id ? "on" : ""}`}
                onClick={() => openSession(s.id)}>
                <span className="side-sess-title">
                  {s.title || "未命名"}
                  {current?.id === s.id && <em>当前</em>}
                </span>
                <span className="side-sess-meta">{s.model || "auto"}</span>
              </div>
            ))}
              </div>
            </>
          )}
        </div>

        {/* 工作区文件树 */}
        <div className="sidebar-section">
          <div className="sidebar-label">工作区</div>
          <div className="sidebar-tree">
            {treePath && (
              <div className="tree-item back" onClick={() => {
                const parts = treePath.split("/");
                parts.pop();
                loadDir(parts.join("/"));
              }}>
                <FolderIcon size={12} /> ..
              </div>
            )}
            {tree.map((e: any, i: number) => (
              <div key={i} className="tree-item"
                onClick={() => e.dir ? loadDir(treePath
                  ? `${treePath}/${e.name}` : e.name) : undefined}>
                {e.dir ? <FolderIcon size={12} /> : <FileIcon size={12} />}
                <span className="tree-name">{e.name}</span>
                {!e.dir && (
                  <span className="tree-size">
                    {e.size > 1024 ? `${(e.size / 1024).toFixed(0)}K` : `${e.size}B`}
                  </span>
                )}
              </div>
            ))}
            {!tree.length && !loadingTree && (
              <div className="tree-empty">空目录</div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
