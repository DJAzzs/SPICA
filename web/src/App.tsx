import { useEffect, useRef, useState } from "react";
import { useSpica, send, resetPlayback, ensureAudio, setMic, setKbdOnly, getState } from "./state";
import { SpicaScene, SceneState } from "./scene";
import { readWaveform } from "./audio";

/** 声纹可视化：真实波形驱动的镜像包络（本地 Analyser，rAF 帧率）。 */
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
          env[i] += (v - env[i]) * 0.35;
        }
      } else {
        for (let i = 0; i < cols; i++) env[i] *= 0.9;
      }
      x.beginPath();
      for (let i = 0; i < cols; i++) {
        const px = (i / (cols - 1)) * w;
        const y = mid - env[i] * (h * 0.42);
        i === 0 ? x.moveTo(px, y) : x.lineTo(px, y);
      }
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
  return <canvas ref={ref} width={720} height={56} />;
}

const ROLE_LABEL: Record<string, string> = {
  user: "我", assistant: "SPICA", tool: "执行", system: "系统",
};

/** 对话面板：消息流 + 实时转写气泡 + 键盘输入。 */
function Chat({ st, partial, kbdOnly, onEnableVoice }: {
  st: string; partial: string; kbdOnly: boolean; onEnableVoice: () => void;
}) {
  const msgs = useSpica((s) => s.msgs);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs.length, partial]);

  const submit = () => {
    const text = input.trim();
    if (!text) return;
    send({ t: "text_input", text });
    setInput("");
  };

  return (
    <div className="chat">
      <div className="chat-scroll" ref={scrollRef}>
        {msgs.length === 0 && (
          <div className="chat-empty">
            说「Hey, SPICA」唤醒，或直接在下方输入任务。<br />
            语音和键盘走同一条管线：改写 → 路由 → DSH 执行。
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <div className="chat-role">{ROLE_LABEL[m.role] || m.role}</div>
            <div className="chat-text">{m.text}</div>
          </div>
        ))}
        {st === "listen" && (
          <div className="chat-msg user ghost">
            <div className="chat-role">正在听…</div>
            <div className="chat-text">{partial || "（说话中）"}</div>
          </div>
        )}
      </div>
      {kbdOnly ? (
        <div className="kbd-hint" onClick={onEnableVoice}>
          语音未启用 —— 点击这里重新开启麦克风
        </div>
      ) : (
        <WaveLine />
      )}
      <div className="chat-input">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          placeholder="输入任务，回车发送（无需唤醒词）"
        />
        <button className="btn primary" onClick={submit}>发送</button>
      </div>
    </div>
  );
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
  const route = useSpica((s) => s.route);
  const steps = useSpica((s) => s.steps);
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

  async function activate() {
    try {
      const { startMic } = await import("./audio");
      await startMic();
      ensureAudio();
      setKbdOnly(false);
      setMic(true);
    } catch (e: any) {
      setMic(false, String(e?.message || e));
    }
  }

  // 已授权过麦克风则自动恢复；仅键盘模式直接进主界面
  useEffect(() => {
    (async () => {
      if (localStorage.getItem("spica-kbd") !== "1") {
        try {
          const perm = await navigator.permissions.query({ name: "microphone" as PermissionName });
          if (perm.state === "granted") await activate();
        } catch { /* 浏览器不支持查询则等待点击 */ }
      }
    })();
  }, []);
  const [kbdOnly, setKbdState] = useState(localStorage.getItem("spica-kbd") === "1");

  if (farewell) {
    return (
      <div className="farewell">
        <div className="name">SPICA</div>
        <div className="sub">已休眠 · 会话已存档 · 重启请运行 make up</div>
      </div>
    );
  }

  // ---------- 空态引导层：麦克风未开启（仅键盘模式跳过） ----------
  if (!micOn && !kbdOnly) {
    return (
      <div className="onboard" onClick={activate}>
        <div className="card">
          <div className="brand">
            <span className="name">SPICA</span>
            <span className="sub">语音优先 · 本地 Agent 操控台</span>
          </div>
          <div className="how">
            <div className="row"><b>唤醒</b>说「Hey, SPICA」或「嘿SPICA」</div>
            <div className="row"><b>下达任务</b>语音或键盘输入（改写后交给 DSH 执行）</div>
            <div className="row"><b>控制</b>「暂停」「继续」，插话随时可说</div>
            <div className="row"><b>结束</b>「Bye, SPICA」或「拜拜SPICA」存档关停</div>
          </div>
          <div className="cta">点击任意处，允许麦克风 → 语音与对话模式同时可用</div>
          {micError && (
            <div className="err">麦克风开启失败：{micError}</div>
          )}
          <div className="skip" onClick={(e) => e.stopPropagation()}>
            <button className="btn" onClick={() => {
              setKbdOnly(true); setKbdState(true);
            }}>仅用键盘（不用语音）</button>
            <a className="btn" href="#/diagnose">硬件诊断</a>
          </div>
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

  return (
    <div className="stage">
      <canvas ref={canvasRef} className="scene-canvas" />

      <header className="topbar">
        <div className="brand">
          <span className="name">SPICA</span>
          <span className="sub">{STATE_KICKER[st] || ""}{route && st === "exec" ? ` · ${route.model ?? ""}` : ""}</span>
        </div>
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
      </header>

      <div className="main-col">
        <Chat st={st} partial={partial} kbdOnly={kbdOnly} onEnableVoice={activate} />
      </div>

      <div className={`state-dot ${wakeFlash && Date.now() - wakeFlash < 1500 ? "wake" : ""} ${st === "confirm_shutdown" ? "confirm" : ""}`} />
    </div>
  );
}
