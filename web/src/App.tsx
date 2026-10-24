import { useEffect, useRef, useState } from "react";
import { useSpica, send, resetPlayback, ensureAudio, setMic } from "./state";
import { SpicaScene, SceneState } from "./scene";
import { readWaveform } from "./audio";

/** 声纹可视化：真实波形驱动的镜像包络（本地 Analyser，rAF 帧率）。
 * 说话时上下起伏明显，安静时近乎平直。 */
function WaveLine() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current!;
    const x = c.getContext("2d")!;
    let raf = 0;
    const cols = 96;
    const env = new Float32Array(cols);
    let mist = "#a8c3c0";
    const refresh = () => {
      mist = getComputedStyle(document.documentElement)
        .getPropertyValue("--mist").trim() || mist;
    };
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const w = c.width, h = c.height, mid = h / 2;
      x.clearRect(0, 0, w, h);
      const wave = readWaveform();
      if (wave) {
        for (let i = 0; i < cols; i++) {
          let m = 0;
          const s = Math.floor((i * wave.length) / cols);
          const e = Math.floor(((i + 1) * wave.length) / cols);
          for (let j = s; j < e; j++) m = Math.max(m, Math.abs(wave[j] - 128));
          const v = Math.min(1, (m / 128) * 1.6);
          env[i] += (v - env[i]) * 0.35;      // 平滑跟随
        }
      } else {
        for (let i = 0; i < cols; i++) env[i] *= 0.9;
      }
      // 上包络
      x.beginPath();
      for (let i = 0; i < cols; i++) {
        const px = (i / (cols - 1)) * w;
        const y = mid - env[i] * (h * 0.42);
        i === 0 ? x.moveTo(px, y) : x.lineTo(px, y);
      }
      // 下包络（镜像）
      for (let i = cols - 1; i >= 0; i--) {
        const px = (i / (cols - 1)) * w;
        x.lineTo(px, mid + env[i] * (h * 0.42));
      }
      x.closePath();
      x.globalAlpha = 0.16; x.fillStyle = mist; x.fill();
      x.globalAlpha = 0.9; x.strokeStyle = mist; x.lineWidth = 1.5; x.stroke();
      x.globalAlpha = 1;
    };
    refresh();
    const themeTimer = setInterval(refresh, 2000);
    draw();
    return () => { cancelAnimationFrame(raf); clearInterval(themeTimer); };
  }, []);
  return <canvas ref={ref} width={720} height={80} />;
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
  const connected = useSpica((s) => s.connected);
  const micOn = useSpica((s) => s.micOn);
  const micError = useSpica((s) => s.micError);

  const [wizardDone, setWizardDone] = useState<boolean | null>(null);
  const [skipWizard, setSkipWizard] = useState(false);
  useEffect(() => { if (settings) setWizardDone(!!settings.wizard_done); }, [settings]);
  useEffect(() => { if (wakeFlash) localStorage.setItem("spica-waked", "1"); }, [wakeFlash]);
  const hasWaked = localStorage.getItem("spica-waked") === "1";
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

  useEffect(() => { if (st === "shutdown") resetPlayback(); }, [st]);

  /** 点击任意处：授权麦克风（浏览器手势要求）+ 解锁播放。 */
  async function activate() {
    try {
      const { startMic } = await import("./audio");
      await startMic();
      ensureAudio();
      setMic(true);
    } catch (e: any) {
      setMic(false, String(e?.message || e));
    }
  }

  if (farewell) {
    return (
      <div className="farewell">
        <div className="name">SPICA</div>
        <div className="sub">已休眠 · 会话已存档 · 重启请运行 make up</div>
      </div>
    );
  }

  // ---------- 空态引导层：麦克风未开启 ----------
  if (!micOn) {
    return (
      <div className="onboard" onClick={activate}>
        <div className="card">
          <div className="brand">
            <span className="name">SPICA</span>
            <span className="sub">语音优先 · 本地 Agent 操控台</span>
          </div>
          <div className="how">
            <div className="row"><b>唤醒</b>说「Hey, SPICA」或「嘿SPICA」</div>
            <div className="row"><b>下达任务</b>用一句话描述，SPICA 会改写后交给 DSH 执行</div>
            <div className="row"><b>控制</b>「暂停」「继续」，插话随时可说</div>
            <div className="row"><b>结束</b>「Bye, SPICA」或「拜拜SPICA」存档关停</div>
          </div>
          <div className="cta">点击任意处，允许麦克风 → 就可以说话了</div>
          {micError && (
            <div className="err">
              麦克风开启失败：{micError}
              <br />（可先到 <a href="#/diagnose" onClick={(e) => e.stopPropagation()}
                style={{ color: "var(--accent)" }}>诊断页</a> 检查设备）
            </div>
          )}
        </div>
      </div>
    );
  }

  // ---------- 首启向导引导（一次性） ----------
  if (wizardDone === false && !skipWizard) {
    return (
      <div className="onboard" style={{ cursor: "default" }}>
        <div className="card">
          <div className="how">
            <div className="row"><b>① 声纹</b>让 SPICA 记住你的声音，只回应你</div>
            <div className="row"><b>② 校准</b>测试唤醒词命中率</div>
            <div className="row"><b>③ 音色</b>挑一个喜欢的声音</div>
          </div>
          <div className="skip">
            <a className="btn primary" href="#/wizard">进入向导（约 1 分钟）</a>
            <button className="btn" onClick={() => {
              setSkipWizard(true);
              send({ t: "settings_patch", patch: { wizard_done: true } });
            }}>跳过，直接用</button>
          </div>
        </div>
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

        {st === "idle" && !hasWaked && (
          <div className="idle-hint">
            待命中 —— 说 <span className="wake-word">「Hey, SPICA」</span>唤醒我
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
          {ttsSpeaking ? <span>播报中</span> : null}
          <span className={`conn ${connected ? "ok" : ""}`} title={connected ? "已连接" : "重连中"} />
          <a href="#/diagnose">诊断</a>
          <a href="#/wizard">向导</a>
          <a href="#/settings">设置</a>
          <a href="#/review">审阅</a>
          <a onClick={() => send({ t: "shutdown_now" })}>关停</a>
        </div>
      )}
    </div>
  );
}
