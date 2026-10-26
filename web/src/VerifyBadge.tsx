import { useSpica } from "./state";

/** 验证结果徽章 — 显示在 turn-done 卡片下方。 */
export default function VerifyBadge({ report }: { report: any }) {
  if (!report) return null;

  const icon = report.overall === "PASS" ? "✓"
    : report.overall === "FAIL" ? "✗" : "⚠";
  const cls = report.overall === "PASS" ? "pass"
    : report.overall === "FAIL" ? "fail" : "warn";

  const layerIcons: Record<number, string> = { 0: "L0", 1: "L1", 2: "L2", 3: "L3" };

  return (
    <div className={`verify-badge ${cls}`}>
      <span className="vb-icon">{icon}</span>
      <span className="vb-text">
        {report.overall === "PASS" ? "验证通过" :
         report.overall === "FAIL" ? "验证失败" : "验证通过（有警告）"}
      </span>
      <span className="vb-layers">
        {report.layers_used?.map((l: number) =>
          layerIcons[l] || `L${l}`).join(" + ")}
      </span>
      <span className="vb-time">{report.elapsed_ms}ms</span>

      {/* 展开详情 */}
      <details className="vb-detail">
        <summary>详情</summary>
        {report.checks?.map((c: any, i: number) => (
          <div key={i} className={`vb-check ${c.pass ? "ok" : "bad"}`}>
            <span className="vb-check-layer">L{c.layer}</span>
            <span className="vb-check-type">{c.type}</span>
            <span className="vb-check-status">{c.pass ? "✓" : "✗"}</span>
            <span className="vb-check-detail">{c.detail}</span>
            {c.issues?.length > 0 && (
              <div className="vb-issues">
                {c.issues.map((issue: any, j: number) => (
                  <div key={j} className={`vb-issue sev-${issue.severity}`}>
                    [{issue.severity}] {issue.description}
                    {issue.suggestion && ` → ${issue.suggestion}`}
                  </div>
                ))}
              </div>
            )}
            {c.contradictions?.length > 0 && (
              <div className="vb-issues">
                {c.contradictions.map((c2: any, j: number) => (
                  <div key={j} className="vb-issue sev-high">
                    声明"{c2.claim}" 实际"{c2.actual}"
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </details>
    </div>
  );
}
