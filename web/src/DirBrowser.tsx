import { useEffect, useState } from "react";
import { FolderIcon, FileIcon } from "./icons";

/** 目录浏览器 v2：直接输入路径 + 新建/重命名/删除文件夹。 */
export default function DirBrowser({ initial = "/", onPick, onClose }: {
  initial?: string; onPick: (path: string) => void; onClose: () => void;
}) {
  const [path, setPath] = useState(initial);
  const [inputPath, setInputPath] = useState(initial);
  const [data, setData] = useState<{ path: string; parent: string;
    dirs: string[]; files: { name: string; size: number }[] } | null>(null);
  const [action, setAction] = useState<"" | "new" | "rename">("");
  const [targetDir, setTargetDir] = useState("");
  const [inputVal, setInputVal] = useState("");

  const load = (p: string) => {
    fetch(`/api/files/browse?path=${encodeURIComponent(p)}`)
      .then(r => r.json())
      .then(d => { setData(d); setInputPath(d.path || p); })
      .catch(() => setData(null));
  };

  useEffect(() => { load(path); }, [path]);

  const go = (p: string) => { setPath(p); setAction(""); };
  const refresh = () => load(path);

  const doMkdir = async () => {
    if (!inputVal.trim()) return;
    await fetch("/api/files/mkdir", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: `${data?.path}/${inputVal.trim()}`.replace("//", "/") }),
    });
    setInputVal(""); setAction(""); refresh();
  };

  const doRename = async () => {
    if (!inputVal.trim() || !targetDir) return;
    await fetch("/api/files/rename", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        old: `${data?.path}/${targetDir}`.replace("//", "/"),
        new: `${data?.path}/${inputVal.trim()}`.replace("//", "/"),
      }),
    });
    setInputVal(""); setAction(""); setTargetDir(""); refresh();
  };

  const doDelete = async (dir: string) => {
    await fetch("/api/files/delete", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: `${data?.path}/${dir}`.replace("//", "/") }),
    });
    refresh();
  };

  return (
    <div className="db2">
      <div className="db2-path-row">
        <input className="db2-path-input" value={inputPath}
          onChange={e => setInputPath(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") go(inputPath); }}
          placeholder="输入路径…" />
        <button className="db2-go" onClick={() => go(inputPath)}>前往</button>
      </div>
      <div className="db2-toolbar">
        {path !== "/" && (
          <button className="db2-tool" onClick={() => go(data?.parent || "/")}>↑ 上级</button>
        )}
        <button className="db2-tool" onClick={() => { setAction("new"); setInputVal(""); }}>
          ＋ 新建文件夹
        </button>
      </div>
      {action === "new" && (
        <div className="db2-action">
          <input value={inputVal} onChange={e => setInputVal(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") doMkdir();
              if (e.key === "Escape") setAction(""); }}
            placeholder="文件夹名称…" autoFocus />
          <button onClick={doMkdir}>创建</button>
          <button onClick={() => setAction("")}>取消</button>
        </div>
      )}
      {action === "rename" && (
        <div className="db2-action">
          <span>重命名「{targetDir}」→</span>
          <input value={inputVal} onChange={e => setInputVal(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") doRename();
              if (e.key === "Escape") setAction(""); }}
            autoFocus />
          <button onClick={doRename}>确定</button>
          <button onClick={() => { setAction(""); setTargetDir(""); }}>取消</button>
        </div>
      )}
      <div className="db2-list">
        {path !== "/" && (
          <div className="db2-item up" onClick={() => go(data?.parent || "/")}>
            <FolderIcon size={14} /> ..
          </div>
        )}
        {(data?.dirs || []).map(d => (
          <div key={d} className="db2-item dir">
            <span className="db2-item-name"
              onClick={() => go(`${data?.path}/${d}`.replace("//", "/"))}>
              <FolderIcon size={14} /> {d}
            </span>
            <span className="db2-item-actions">
              <button title="重命名" onClick={() => {
                setAction("rename"); setTargetDir(d); setInputVal(d); }}>✎</button>
              <button title="删除" className="del"
                onClick={() => { if (confirm(`删除「${d}」？`)) doDelete(d); }}>✕</button>
            </span>
          </div>
        ))}
        {(data?.files || []).map(f => (
          <div key={f.name} className="db2-item file">
            <span className="db2-item-name"><FileIcon size={14} /> {f.name}</span>
            <span className="db2-size">
              {f.size > 1024 ? `${(f.size / 1024).toFixed(0)}K` : `${f.size}B`}
            </span>
          </div>
        ))}
        {!data?.dirs?.length && !data?.files?.length && (
          <div className="db2-empty">空目录</div>
        )}
      </div>
      <button className="db2-pick" onClick={() => {
        onPick(data?.path || path); onClose();
      }}>选定此目录</button>
    </div>
  );
}
