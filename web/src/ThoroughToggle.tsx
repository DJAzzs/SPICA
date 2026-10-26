import { useSpica, send } from "./state";

/** 缜密模式开关（验证管线 L0+L1+L2）。 */
export default function ThoroughToggle() {
  const current = useSpica((s) => s.currentSession);
  const on = !!current?.thorough;

  return (
    <button
      className={`topbar-toggle ${on ? "on" : ""}`}
      onClick={() =>
        send({ t: "session_update", id: current?.id, patch: { thorough: !on } })}
      title={on ? "缜密模式开启：任务完成后自动验证" : "缜密模式关闭"}>
      <span className="toggle-icon">◎</span>
      <span className="toggle-label">缜密</span>
      <span className={`toggle-track ${on ? "on" : ""}`}>
        <span className={`toggle-knob ${on ? "on" : ""}`} />
      </span>
    </button>
  );
}
