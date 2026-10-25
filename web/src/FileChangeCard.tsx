import { useState } from "react";

/** 文件变更摘要卡：任务完成后展示编辑过的文件（按变更行数降序，
 *  默认 3 个，可展开全部；深色=液态玻璃，浅色=便利贴）。 */
export default function FileChangeCard({ files }: {
  files: { path: string; rel: boolean; a: number; r: number }[];
}) {
  const [expanded, setExpanded] = useState(false);
  if (!files || files.length === 0) return null;

  const shown = expanded ? files : files.slice(0, 3);
  const total = files.length;
  const totalAdded = files.reduce((s, f) => s + f.a, 0);
  const totalRemoved = files.reduce((s, f) => s + f.r, 0);

  return (
    <div className="file-change-card">
      <div className="fc-head">
        <span className="fc-title">已编辑 {total} 个文件</span>
        <span className="fc-total-diff">
          {totalAdded > 0 && <span className="diff-add">+{totalAdded}</span>}
          {totalRemoved > 0 && <span className="diff-del">-{totalRemoved}</span>}
        </span>
      </div>
      <div className="fc-list">
        {shown.map((f, i) => {
          const name = f.path.split("/").pop() || f.path;
          const dir = f.path.includes("/")
            ? f.path.slice(0, f.path.lastIndexOf("/")) : "";
          return (
            <div key={i} className="fc-item">
              <span className="fc-name" title={f.path}>
                {name}
              </span>
              {dir && <span className="fc-dir" title={f.path}>{dir}/</span>}
              <span className="fc-diff">
                {f.a > 0 && <span className="diff-add">+{f.a}</span>}
                {f.r > 0 && <span className="diff-del">-{f.r}</span>}
              </span>
            </div>
          );
        })}
      </div>
      {total > 3 && (
        <button className="fc-expand" onClick={() => setExpanded(!expanded)}>
          {expanded ? "收起" : `全部 ${total} 个文件`}
        </button>
      )}
    </div>
  );
}
