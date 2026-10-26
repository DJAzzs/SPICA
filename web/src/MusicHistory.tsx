import { useEffect, useState } from "react";

interface HistEntry {
  title: string; artist: string; keyword: string; ts: number;
}

/** 音乐播放历史 — 顶栏 🎵 弹出面板。 */
export default function MusicHistory() {
  const [open, setOpen] = useState(false);
  const [list, setList] = useState<HistEntry[]>([]);

  useEffect(() => {
    if (open) load();
  }, [open]);

  const load = async () => {
    try {
      const r = await fetch("/api/music/history");
      const j = await r.json();
      setList(j.list || []);
    } catch {}
  };

  const deleteEntry = async (i: number) => {
    await fetch(`/api/music/history/${i}`, { method: "DELETE" });
    load();
  };

  const clearAll = async () => {
    if (!confirm("清空全部播放历史并重置音乐偏好？")) return;
    await fetch("/api/music/history", { method: "DELETE" });
    load();
  };

  return (
    <div className="mh-trigger">
      <button className="mh-btn" onClick={() => setOpen(!open)}
        title="播放历史">🎵</button>
      {open && (
        <div className="mh-panel">
          <div className="mh-head">
            <span className="mh-title">播放历史</span>
            <button className="mh-clear" onClick={clearAll}>清空</button>
            <button className="mh-close" onClick={() => setOpen(false)}>✕</button>
          </div>
          <div className="mh-list">
            {list.length === 0 && (
              <div className="mh-empty">暂无播放记录</div>
            )}
            {list.slice().reverse().map((h, i) => (
              <div key={i} className="mh-item">
                <span className="mh-name">{h.title}</span>
                <span className="mh-artist">{h.artist}</span>
                <span className="mh-time">
                  {new Date(h.ts * 1000).toLocaleDateString("zh-CN",
                    { month: "short", day: "numeric" })}
                </span>
                <button className="mh-del"
                  onClick={() => deleteEntry(list.length - 1 - i)}>✕</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
