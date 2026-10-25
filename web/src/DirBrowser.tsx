import { useEffect, useState } from "react";
import { FolderIcon, FileIcon } from "./icons";

/** 目录浏览器：选工作区用（模态弹层）。 */
export default function DirBrowser({ initial = "/", onPick, onClose, inline }: {
  initial?: string; onPick: (path: string) => void; onClose: () => void;
  inline?: boolean;
}) {
  const [path, setPath] = useState(initial);
  const [data, setData] = useState<{ path: string; parent: string;
    dirs: string[]; files: { name: string; size: number }[] } | null>(null);

  useEffect(() => {
    fetch(`/api/files/browse?path=${encodeURIComponent(path)}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null));
  }, [path]);

  const panel = (
      <>
        {!inline && <div className="db-head">
          <span className="db-title">选择工作区</span>
          <button className="db-close" onClick={onClose}>✕</button>
        </div>}
        <div className="db-path">{data?.path || path}</div>
        <div className="db-list">
          {path !== "/" && (
            <div className="db-item up" onClick={() => setPath(data?.parent || "/")}>
              <FolderIcon size={14} /> ..
            </div>
          )}
          {(data?.dirs || []).map(d => (
            <div key={d} className="db-item dir"
              onClick={() => setPath(`${data?.path}/${d}`.replace("//", "/"))}>
              <FolderIcon size={14} />
              <span>{d}</span>
            </div>
          ))}
          {(data?.files || []).map(f => (
            <div key={f.name} className="db-item file">
              <FileIcon size={14} />
              <span>{f.name}</span>
              <span className="db-size">
                {f.size > 1024 ? `${(f.size / 1024).toFixed(0)}K` : `${f.size}B`}</span>
            </div>
          ))}
          {!data?.dirs.length && !data?.files.length && (
            <div className="db-empty">空目录</div>
          )}
        </div>
        <button className="db-pick" onClick={() => { onPick(data?.path || path); onClose(); }}>
          选定此目录
        </button>
      </>
  );

  if (inline) return <div className="dir-browser inline">{panel}</div>;
  return (
    <div className="dir-browser-mask" onClick={onClose}>
      <div className="dir-browser" onClick={e => e.stopPropagation()}>{panel}</div>
    </div>
  );
}
