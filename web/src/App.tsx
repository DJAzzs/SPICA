import { useEffect, useRef } from "react";
import { useSpica, send, resetPlayback } from "./state";
import { SpicaScene, SceneState } from "./scene";

/** 声纹线：底部细柔起伏（RMS 驱动，平滑 0.25）。 */
function WaveLine() {
  const ref = useRef<HTMLCanvasElement>(null);
  const rms = useSpica((s) => s.rms);
  const smooth = useRef(0);
  useEffect(() => {
    const c = ref.current!;
    const x = c.getContext("2d")!;
    let raf = 0, t = 0;
    const style = getComputedStyle(document.documentElement);
    const mist = style.getPropertyValue("--mist").trim() || "#a8c3c0";
    const draw = () => {
      t += 0.08;
      smooth.current += (rms - smooth.current) * 0.25;
      const w = c.width, h = c.height;
      x.clearRect(0, 0, w, h);
      x.beginPath();
      x.strokeStyle = mist;
      x.lineWidth = 2;
      const amp = 3 + Math.min(10, smooth.current * 220);
      for (let i = 0; i <= w; i += 4) {
        const y = h / 2 + Math.sin(i * 0.03 + t) * amp * (0.5 + 0.5 * Math.sin(t * 0.35));
        i === 0 ? x.moveTo(i, y) : x.lineTo(i, y);
      }
      x.stroke();
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [rms]);
  return <canvas ref={ref} width={640} height={44} />;
}

const STATE_KICKER: Record<string, string> = {
  idle: "待命 · IDLE",
  listen: "聆听 · LISTEN",
  exec: "正在执行 · EXEC",
  paused: "已暂停 · PAUSED",
  confirm_shutdown: "确认结束？ · CONFIRM",
  shutdown: "休眠 · SHUTDOWN",
};

export default function App() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<SpicaScene | null>(null);
  const st = useSpica((s) => s.state);
  const partial = useSpica((s) => s.partial);
  const finalText = useSpica((s) => s.final);
  const rewriteFinal = useSpica((s) => s.rewriteFinal);
  const rewriteDraft = useSpica((s) => s.rewriteDraft);
  const route = useSpica((s) => s.route);
  const steps = useSpica((s) => s.steps);
  const taskDone = useSpica((s) => s.taskDone);
  const ttsSpeaking = useSpica((s) => s.ttsSpeaking);
  const wakeFlash = useSpica((s) => s.wakeFlash);
  const farewell = useSpica((s) => s.farewell);
  const settings = useSpica((s) => s.settings);
  const demo = document.documentElement.dataset.demo === "1";

  useEffect(() => {
    if (canvasRef.current && !sceneRef.current) {
      sceneRef.current = new SpicaScene(
        canvasRef.current,
        document.documentElement.dataset.theme === "light" ? "light" : "dark");
    }
  }, []);

  useEffect(() => {
    const map: Record<string, SceneState> = {
      idle: "idle", listen: "listen", exec: "exec", paused: "paused",
      confirm_shutdown: "confirm", shutdown: "done",
    };
    sceneRef.current?.setState(map[st] ?? "idle", steps.length);
  }, [st, steps.length]);

  useEffect(() => {
    const unsubRms = setInterval(() => {}, 1000);
    return () => clearInterval(unsubRms);
  }, []);

  useEffect(() => { resetPlayback(); }, [st === "shutdown"]);

  if (farewell) {
    return (
      <div className="farewell">
        <div className="name">SPICA</div>
        <div className="sub">已休眠 · 会话已存档 · 重启请运行 make up</div>
      </div>
    );
  }

  const title = st === "exec" || st === "paused"
    ? (rewriteFinal || finalText)
    : st === "done" ? taskDone : "";

  return (
    <div className="stage">
      <canvas ref={canvasRef} className="scene-canvas" />

      <div className="main-col">
        <div className="brand">
          <span className="name">SPICA</span>
          <span className="sub">语音优先 · 本地 Agent 操控台</span>
        </div>

        {(st === "exec" || st === "paused" || st === "confirm_shutdown") && (
          <div className="task" style={{ animation: "enter 800ms var(--ease)" }}>
            <div className="kicker">{STATE_KICKER[st]}</div>
            <div className="task-title focused">{title.slice(0, 40) || "…"}</div>
            <div className="task-meta">
              {route ? `${route.model ?? ""} · 推理 ${route.difficulty}` : ""}
              {settings?.wake_words ? "" : ""}
            </div>
            <div className="steps">
              {steps.map((s) => (
                <div key={s.i} className={`step-row ${s.status}`}>
                  <span className="dot" />
                  <span className="idx">{String(s.i).padStart(2, "0")}</span>
                  <span className="txt">
                    {s.type === "assistant/message" ? s.text.slice(0, 48) : s.type}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {st === "done" && taskDone && (
          <div className="task" style={{ animation: "enter 800ms var(--ease)" }}>
            <div className="kicker">完成 · DONE</div>
            <div className="task-title">{taskDone.slice(0, 60)}</div>
          </div>
        )}
      </div>

      {/* 改写进度线：草稿即满 */}
      <div className="rewrite-bar">
        <div className="fill" style={{ width: rewriteDraft ? "100%" : rewriteFinal ? "100%" : "0%" }} />
      </div>

      {/* 聆听提示：低对比单行（不逐字展示，仅当前 partial 尾部） */}
      {st === "listen" && (
        <div className="listening-hint">
          {partial ? `… ${partial.slice(-24)}` : "在听"}
        </div>
      )}
      <div className="wave-wrap"><WaveLine /></div>

      <div className={`state-dot ${wakeFlash && Date.now() - wakeFlash < 1500 ? "wake" : ""} ${st === "confirm_shutdown" ? "confirm" : ""}`} />

      {!demo && (
        <div className="tools">
          {ttsSpeaking ? <span>播报中</span> : <span />}
          <a href="#/diagnose">诊断</a>
          <a href="#/wizard">向导</a>
          <a href="#/settings">设置</a>
          <a href="#/review">审阅</a>
          <a onClick={() => send({ t: "shutdown_now" })} style={{ cursor: "pointer" }}>关停</a>
        </div>
      )}
    </div>
  );
}
