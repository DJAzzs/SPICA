import { useRef, useState } from "react";
import { useSpica } from "./state";

/** 底部运行统计栏：IDE 风格极细灰字，hover 浮出详情玻璃卡。 */
function CtxDetail({ stats }: { stats: any }) {
  const [show, setShow] = useState(false);
  const timer = useRef<number>(0);

  const onEnter = () => {
    timer.current = window.setTimeout(() => setShow(true), 1000);
  };
  const onLeave = () => {
    clearTimeout(timer.current);
    setShow(false);
  };

  const bd = stats.breakdown || {};
  const items = [
    { label: "系统提示词", key: "systemPrompt", color: "var(--mist)" },
    { label: "工具定义", key: "toolDefinitions", color: "var(--mustard)" },
    { label: "对话消息", key: "messages", color: "var(--sand)" },
    { label: "其他", key: "other", color: "var(--lilac)" },
  ].filter(i => bd[i.key]);
  const total = items.reduce((s, i) => s + bd[i.key], 0) || stats.ctx_used || 1;

  const fmtK = (n: number) =>
    n >= 1000 ? `${(n / 1000).toFixed(1)}K` : `${n}`;

  return (
    <div className="ctx-detail" onMouseEnter={onEnter} onMouseLeave={onLeave}>
      <div className="ctx-hover-zone" onMouseEnter={onEnter} onMouseLeave={onLeave} />
      {show && (
        <div className="ctx-detail-card">
          {/* 多色占比条 */}
          <div className="ctx-bar-multi">
            {items.map(i => (
              <span key={i.key} style={{
                width: `${(bd[i.key] / total) * 100}%`,
                background: i.color }} />
            ))}
          </div>
          {items.map(i => (
            <div key={i.key} className="ctx-detail-row">
              <span className="ctx-dot" style={{ background: i.color }} />
              <span className="ctx-label">{i.label}</span>
              <span className="ctx-val">~{fmtK(bd[i.key])}</span>
              <span className="ctx-pct">
                {((bd[i.key] / total) * 100).toFixed(0)}%
              </span>
            </div>
          ))}
          <div className="ctx-detail-total">
            合计 ~{fmtK(total)} / {stats.ctx_win
              ? fmtK(stats.ctx_win) : "?"}
          </div>
        </div>
      )}
    </div>
  );
}

export default function StatsBar() {
  const stats = useSpica((s) => s.stats);
  if (!stats) return null;

  const fmtK = (n: number) =>
    n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
  const ctxColor = stats.ctx_pct > 80 ? "var(--accent)"
    : stats.ctx_pct > 60 ? "var(--mustard)" : "";

  return (
    <div className="stats-bar" title="运行统计">
      <span className="stat-item" title="当前驱动模型">
        <span className="stat-dot model" />{stats.model || "auto"}
      </span>
      <span className="stat-item" title="输出速度"
        style={{ visibility: stats.speed > 0 ? "visible" : "hidden" }}>
        <span className="stat-dot speed" />{stats.speed} tok/s
      </span>
      <span className="stat-item ctx-hover" style={{ color: ctxColor || undefined }}>
        <span className="stat-dot ctx" style={{ background: ctxColor || undefined }} />
        ctx {stats.ctx_pct}%
        <span className="stat-bar-track">
          <span className="stat-bar-fill" style={{
            width: `${Math.min(100, stats.ctx_pct)}%`,
            background: ctxColor || "var(--mist)" }} />
        </span>
        <CtxDetail stats={stats} />
      </span>
      <span className="stat-item" title="总轮/步">
        <span className="stat-dot turn" />{stats.turns}轮·{stats.steps}步
      </span>
      <span className="stat-item" title="总 tokens">
        <span className="stat-dot token" />{fmtK(stats.total)} tok
      </span>

      {/* hover 详情 */}
      <div className="stats-detail">
        <div className="stats-detail-row">
          <span>输入</span><b>{stats.total_in.toLocaleString()}</b>
        </div>
        <div className="stats-detail-row">
          <span>输出</span><b>{stats.total_out.toLocaleString()}</b>
        </div>
        <div className="stats-detail-row">
          <span>合计</span><b>{stats.total.toLocaleString()}</b>
        </div>
        <div className="stats-detail-row">
          <span>上下文</span><b>{stats.ctx_used.toLocaleString()} /
            {stats.ctx_win ? stats.ctx_win.toLocaleString() : "?"}</b>
        </div>
        <div className="stats-detail-row">
          <span>速度</span><b>{stats.speed > 0 ? `${stats.speed} tok/s` : "—"}</b>
        </div>
        <div className="stats-detail-row">
          <span>轮/步</span><b>{stats.turns} / {stats.steps}</b>
        </div>
      </div>
    </div>
  );
}
