import { useSpica } from "./state";

/** 底部运行统计栏：IDE 风格极细灰字，hover 浮出详情玻璃卡。 */
export default function StatsBar() {
  const stats = useSpica((s) => s.stats);
  if (!stats || !stats.total) return null;

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
      <span className="stat-item" title={`上下文 ${stats.ctx_used}/${stats.ctx_win}`}
        style={{ color: ctxColor || undefined }}>
        <span className="stat-dot ctx" style={{ background: ctxColor || undefined }} />
        ctx {stats.ctx_pct}%
        <span className="stat-bar-track">
          <span className="stat-bar-fill" style={{
            width: `${Math.min(100, stats.ctx_pct)}%`,
            background: ctxColor || "var(--mist)" }} />
        </span>
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
