import { useEffect, useState } from "react";
import { useSpica } from "./state";

/** 工作区文件浏览器：浏览当前会话工作区，查看文本文件。 */
export default function Files() {
  const currentSession = useSpica((s) => s.currentSession);
  const [sub, setSub] = useState("");
  const [data, setData] = useState<any>(null);
  const [file, setFile] = useState<{ path: string; content: string } | null>(null);
  const [err, setErr] = useState("");

  const load = async (s: string) => {
    setErr(""); setFile(null);
    const r = await fetch(`/api/files/list?sub=${encodeURIComponent(s)}`);
    const j = await r.json();
    if (j.error) setErr(j.error);
    setData(j);
    setSub(s);
  };
  useEffect(() => { load(""); }, []);

  const open = async (name: string, dir: boolean) => {
    if (dir) { load(sub ? `${sub}/${name}` : name); return; }
    const p = sub ? `${sub}/${name}` : name;
    const r = await fetch(`/api/files/read?path=${encodeURIComponent(p)}`);
    const j = await r.json();
    if (j.error) setErr(j.error);
    else setFile(j);
  };

  const crumbs = sub ? sub.split("/") : [];
  const fmt = (n: number) =>
    n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)}M`
    : n > 1024 ? `${(n / 1024).toFixed(0)}K` : `${n}B`;

  return (
    <div className="panel">
      <div className="inner" style={{ width: 760 }}>
        <h1>工作区文件</h1>
        <div className="hint" style={{ marginBottom: 16 }}>
          {currentSession?.cwd || "…"}
        </div>

        <div className="file-crumbs">
          <a onClick={() => load("")}>根目录</a>
          {crumbs.map((c, i) => (
            <span key={i}>
              <span className="file-sep">/</span>
              <a onClick={() => load(crumbs.slice(0, i + 1).join("/"))}>{c}</a>
            </span>
          ))}
        </div>

        {err && <div className="hint status-fail">{err}</div>}

        {file ? (
          <div className="file-view">
            <div className="file-view-head">
              <span>{file.path}</span>
              <button className="btn" onClick={() => setFile(null)}>关闭</button>
            </div>
            <pre>{file.content}</pre>
          </div>
        ) : (
          <div className="file-list">
            {sub && (
              <div className="file-row" onClick={() => {
                const parts = sub.split("/");
                parts.pop();
                load(parts.join("/"));
              }}>📁 ..</div>
            )}
            {(data?.entries || []).map((e: any) => (
              <div key={e.name} className="file-row"
                onClick={() => open(e.name, e.dir)}>
                <span>{e.dir ? "📁" : "📄"} {e.name}</span>
                {!e.dir && <span className="file-size">{fmt(e.size)}</span>}
              </div>
            ))}
            {data && !data.entries?.length && !sub && (
              <div className="hint">工作区还是空的——发个任务让它干活。</div>
            )}
          </div>
        )}

        <div className="btn-row"><a className="btn" href="#/">返回</a></div>
      </div>
    </div>
  );
}
