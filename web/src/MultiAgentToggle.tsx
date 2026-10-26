import { useSpica, send } from "./state";

/** 多智能体开关（PHLOX 并行调度）。 */
export default function MultiAgentToggle() {
  const current = useSpica((s) => s.currentSession);
  const on = !!current?.multi_agent;

  return (
    <button
      className={`topbar-toggle ${on ? "on" : ""}`}
      onClick={() =>
        send({ t: "session_update", id: current?.id, patch: { multi_agent: !on } })}
      title={on ? "多智能体开启：PHLOX 并行调度" : "多智能体关闭"}>
      <span className="toggle-icon">👥</span>
      <span className="toggle-label">多智能体</span>
      <span className={`toggle-track ${on ? "on" : ""}`}>
        <span className={`toggle-knob ${on ? "on" : ""}`} />
      </span>
    </button>
  );
}
