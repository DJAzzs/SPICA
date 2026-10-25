import { useState } from "react";
import { send } from "./state";
import DirBrowser from "./DirBrowser";

/** 新会话弹窗：表单优先（路径输入 + 浏览按钮），浏览器按需展开。 */
export default function NewSessionModal({ onClose }: { onClose: () => void }) {
  const [cwd, setCwd] = useState("/home/dja");
  const [browsing, setBrowsing] = useState(false);
  const [perm, setPerm] = useState("workspace-write");

  const create = () => {
    send({ t: "session_new" });
    if (cwd.trim()) {
      send({ t: "session_update", patch: { cwd: cwd.trim(), perm } });
    }
    onClose();
  };

  return (
    <div className="ns-modal-mask" onClick={onClose}>
      <div className="ns-modal" onClick={e => e.stopPropagation()}>
        <div className="ns-head">
          <span className="ns-title">创建新会话</span>
          <button className="ns-close" onClick={onClose}>✕</button>
        </div>
        <div className="ns-body">
          {browsing ? (
            <DirBrowser
              initial={cwd || "/"}
              onPick={p => setCwd(p)}
              onClose={() => setBrowsing(false)} />
          ) : (
            <div className="ns-form">
              <div className="ns-field">
                <label>工作区路径</label>
                <div className="ns-cwd-row">
                  <input className="ns-cwd-input" value={cwd}
                    onChange={e => setCwd(e.target.value)}
                    placeholder="/home/用户名/项目"
                    onKeyDown={e => { if (e.key === "Enter") create(); }} />
                  <button className="ns-browse-trigger"
                    onClick={() => setBrowsing(true)} title="浏览">📁</button>
                </div>
              </div>
              <div className="ns-field">
                <label>权限</label>
                <div className="ns-perms">
                  {[["read-only", "只读"],
                    ["workspace-write", "工作区写入"],
                    ["danger-full-access", "完全访问"]].map(([v, label]) => (
                    <button key={v}
                      className={"ns-perm" + (perm === v ? " on" : "")}
                      onClick={() => setPerm(v)}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
        {!browsing && (
          <button className="ns-create" onClick={create}>创建会话</button>
        )}
      </div>
    </div>
  );
}
