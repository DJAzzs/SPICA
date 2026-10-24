import { useEffect, useRef, useState } from "react";
import { useSpica, send, resetPlayback, ensureAudio, setMic, setKbdOnly, getState, set, toast as toastMsg } from "./state";
import { SpicaScene, SceneState } from "./scene";
import Wave from "./Wave";
import Markdown from "./Markdown";
import { MicIcon, PlusIcon, SendIcon } from "./icons";

const ROLE_LABEL: Record<string, string> = {
  user: "用户", assistant: "SPICA", tool: "执行", system: "系统",
};

/** 对话面板：消息流 + 实时转写气泡 + 键盘输入。 */
function Chat({ st, partial, kbdOnly, connected, onEnableVoice }: {
  st: string; partial: string; kbdOnly: boolean;
  connected: boolean; onEnableVoice: () => void;
}) {
  const msgs = useSpica((s) => s.msgs);
  const toast = useSpica((s) => s.toast);
  const localListen = useSpica((s) => s.localListen);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");
  const [dragOn, setDragOn] = useState(false);
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs.length, partial]);

  const submit = () => {
    const text = input.trim();
    if (!text || !connected) return;   // 断连静默丢弃 = 假死，必须挡住
    setInput("");
    // 斜杠命令：/plan /compact /export /goal
    const m = text.match(/^\/(\w+)\s*([\s\S]*)$/);
    if (m) {
      const cmd = m[1].toLowerCase();
      if (cmd === "export") {
        send({ t: "slash", cmd: "export", arg: "" });   // 服务端播报+触发下载
        return;
      }
      if (["plan", "compact", "goal"].includes(cmd)) {
        send({ t: "slash", cmd, arg: m[2].trim() });
        return;
      }
      toastMsg(`未知命令 /${cmd}，可用：/plan /compact /export /goal`);
      return;
    }
    send({ t: "text_input", text });
  };

  /** 文件上传（按钮 + 拖拽共用） */
  const upload = async (files: FileList | File[] | null) => {
    if (!files || !(files as any).length) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    try {
      const r = await fetch("/api/files/upload", { method: "POST", body: fd });
      const j = await r.json();
      if (j.error) toastMsg(`上传失败：${j.error}`);
      else toastMsg(`已上传 ${j.saved.length} 个文件`);
    } catch (e: any) {
      toastMsg(`上传失败：${e?.message || e}`);
    }
  };

  /** 麦克风按钮：聆听中=取消；否则手动进入聆听（说话即可，无需唤醒词） */
  const micClick = () => {
    if (kbdOnly) { onEnableVoice(); return; }
    if (st === "listen") {
      set({ localListen: false });
      toastMsg("已取消聆听");
      send({ t: "cancel_listen" });
      return;
    }
    if (!connected) { toastMsg("未连接服务：请在终端运行 make up"); return; }
    // 本地立即反馈；服务器 2.5s 内未接手则提示重启（旧版本无此消息）
    set({ localListen: true });
    toastMsg("正在听，请说话…", 0);
    send({ t: "manual_listen" });
    setTimeout(() => {
      const s = getState();
      if (s.localListen && s.state !== "listen") {
        set({ localListen: false });
        toastMsg("服务器没有响应手动聆听——请在终端执行 make stop && make up 重启后重试");
      }
    }, 2500);
  };

  return (
    <div className="chat"
      onDragOver={(e) => { e.preventDefault(); setDragOn(true); }}
      onDragLeave={() => setDragOn(false)}
      onDrop={(e) => { e.preventDefault(); setDragOn(false); upload(e.dataTransfer.files); }}>
      {dragOn && <div className="drop-hint">松开以上传到工作区 uploads/</div>}
      {toast && <div className="chat-toast">{toast}</div>}
      <div className="chat-scroll" ref={scrollRef}>
        {msgs.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-title">和 SPICA 聊聊</div>
            <div className="chat-empty-line">
              语音唤醒「Hey, SPICA」 · 点击 <MicIcon size={13} /> 直接说 · 或在下方输入
            </div>
            <div className="chat-empty-line dim">
              支持命令：/plan 只读规划 · /compact 压缩上下文 · /goal 长期目标 · /export 导出
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <div className="chat-role">{ROLE_LABEL[m.role] || m.role}</div>
            <div className="chat-text"><Markdown text={m.text} /></div>
          </div>
        ))}
        {st === "listen" || localListen ? (
          <div className="chat-msg user ghost">
            <div className="chat-role">正在听…</div>
            <div className="chat-text">{partial || "（说话中）"}</div>
          </div>
        ) : null}
      </div>
      {kbdOnly ? (
        <div className="kbd-hint" onClick={onEnableVoice}>
          语音未启用 —— 点击这里重新开启麦克风
        </div>
      ) : (
        <Wave />
      )}
      <div className="chat-input">
        <label className="icon-btn" title="上传文件到工作区（也可直接拖拽）">
          <PlusIcon />
          <input type="file" multiple style={{ display: "none" }}
            onChange={(e) => { upload(e.target.files); e.currentTarget.value = ""; }} />
        </label>
        <button className={`icon-btn mic ${st === "listen" || localListen ? "live" : ""}`}
          onClick={micClick} title="点击直接说话（聆听中点击取消）"
          disabled={!connected && !kbdOnly}><MicIcon /></button>
        <input
          type="text"
          value={input}
          disabled={!connected}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          placeholder={connected
            ? "输入任务，回车发送 · / 唤起命令"
            : "未连接服务 —— 请在终端运行 make up 后自动重连"}
        />
        <button className="send-btn" onClick={submit} disabled={!connected}
          title="发送（Enter）"><SendIcon /></button>
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
  const currentSession = useSpica((s) => s.currentSession);
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
        document.documentElement.dataset.theme === "dark" ? "dark" : "light");
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
            <span className="mark" />
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
          <span className="mark" />
          <span className="name">SPICA</span>
          <span className="sub">
            {currentSession?.title
              ? `${currentSession.title} · ${STATE_KICKER[st] || ""}`
              : STATE_KICKER[st] || ""}
            {route && st === "exec" ? ` · ${route.model ?? ""}` : ""}
          </span>
        </div>
        {!demo && (
          <div className="tools">
            <select className="model-select"
              value={currentSession?.model_override || ""}
              onChange={(e) => send({ t: "session_update",
                id: currentSession?.id, patch: { model_override: e.target.value } })}
              title="会话模型（自动=按难度路由）">
              <option value="">模型：自动</option>
              <option value="glm-5.3-flash">glm-5.3-flash</option>
              <option value="glm-5.3">glm-5.3</option>
              <option value="glm-4.6">glm-4.6</option>
            </select>
            {(st === "exec" || st === "paused") && (
              <button className="btn"
                onClick={() => send({ t: "command",
                  name: st === "exec" ? "pause" : "resume" })}>
                {st === "exec" ? "⏸ 暂停任务" : "▶ 继续任务"}
              </button>
            )}
            {ttsSpeaking ? <span>播报中</span> : null}
            <span className={`conn ${connected ? "ok" : ""}`} title={connected ? "已连接" : "重连中"} />
            <a href="#/sessions">会话</a>
            <a href="#/files">文件</a>
            <a href="#/diagnose">诊断</a>
            <a href="#/wizard">向导</a>
            <a href="#/settings">设置</a>
            <a href="#/review">审阅</a>
            <a onClick={() => send({ t: "shutdown_now" })}>关停</a>
          </div>
        )}
      </header>

      <div className="main-col">
        <Chat st={st} partial={partial} kbdOnly={kbdOnly}
          connected={connected} onEnableVoice={activate} />
      </div>

      <div className={`state-dot ${wakeFlash && Date.now() - wakeFlash < 1500 ? "wake" : ""} ${st === "confirm_shutdown" ? "confirm" : ""}`} />
    </div>
  );
}
