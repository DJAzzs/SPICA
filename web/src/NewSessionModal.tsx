import { useState } from "react";
import { send } from "./state";
import DirBrowser from "./DirBrowser";

/** 新会话创建弹窗：工作区浏览 + 权限选择 + 创建。 */
export default function NewSessionModal({ onClose }: { onClose: () => void }) {
  const [cwd, setCwd] = useState("");
  const [browsing, setBrowsing] = useState(true);
  const [perm, setPerm] = useState("workspace-write");

  const create = () => {
    send({ t: "session_new" });
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
            <div className="ns-browse">
              <DirBrowser inline
                initial={cwd || "/"}
                onPick={p => { setCwd(p); setBrowsing(false); }}
                onClose={() => setBrowsing(false)} />
            </div>
          ) : (
            <div className="ns-form">
              <div className="ns-field">
                <label>工作区</label>
                <button className="ns-cwd" onClick={() => setBrowsing(true)}>
                  📁 {cwd || "使用默认工作区"}
                </button>
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
