import { useEffect, useRef, useState } from "react";
import { useSpica, send, resetPlayback, ensureAudio, setMic, setKbdOnly, getState, set, toast as toastMsg, toggleTurn, addPendingFiles, removePendingFile, clearPendingFiles } from "./state";
import Wave from "./Wave";
import Markdown from "./Markdown";
import { MicIcon, PlusIcon, SendIcon, FileIcon } from "./icons";
import ThemeToggle from "./ThemeToggle";
import Backdrop from "./Backdrop";
import MusicBar from "./MusicBar";
import NavRail from "./NavRail";
import StatsBar from "./StatsBar";
import FileChangeCard from "./FileChangeCard";
import Sidebar from "./Sidebar";
import ModelPicker from "./ModelPicker";

const SLASH_COMMANDS: { cmd: string; hint: string }[] = [
  { cmd: "plan",    hint: "只读规划，不改文件：/plan <目标>" },
  { cmd: "compact", hint: "压缩上下文，保留摘要续命" },
  { cmd: "export",  hint: "导出当前会话为 zip" },
  { cmd: "goal",    hint: "长期目标多轮推进：/goal <目标> · /goal stop" },
  { cmd: "music",   hint: "音乐：/music <歌名> · stop · next · taste" },
  { cmd: "memory",  hint: "记忆：add <内容> · user <偏好> · list · remove" },
  { cmd: "skills",  hint: "技能库：list · del <名称>" },
];

const ROLE_LABEL: Record<string, string> = {
  user: "用户", assistant: "SPICA", tool: "执行", system: "系统",
};

/** 对话面板：消息流 + 实时转写气泡 + 键盘输入。 */
function Chat({ st, partial, kbdOnly, connected, onEnableVoice }: {
  st: string; partial: string; kbdOnly: boolean;
  connected: boolean; onEnableVoice: () => void;
}) {
  const msgs = useSpica((s) => s.msgs);
  const turns = useSpica((s) => s.turns);
  const execSince = useSpica((s) => s.execSince);
  const toast = useSpica((s) => s.toast);
  const localListen = useSpica((s) => s.localListen);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");
  const [dragOn, setDragOn] = useState(false);
  const [openThinking, setOpenThinking] = useState<Record<number, boolean>>({});
  const [now, setNow] = useState(Date.now());
  const pendingFiles = useSpica((s) => s.pendingFiles);
  const permissionReq = useSpica((s) => s.permissionReq);
  const [cmdIdx, setCmdIdx] = useState(0);
  const cmdMatches = input.startsWith("/")
    ? SLASH_COMMANDS.filter((c) => ("/" + c.cmd).startsWith(input.toLowerCase())
        || input.toLowerCase().startsWith("/" + c.cmd + " "))
    : [];
  const cmdOpen = cmdMatches.length > 0 && !input.includes(" ");

  // 执行中每秒跳动（运行计时）
  useEffect(() => {
    if (st !== "exec") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [st]);

  const fmtDur = (sec: number) => sec >= 60
    ? `${Math.floor(sec / 60)}分${Math.round(sec % 60)}秒`
    : `${Math.round(sec)}秒`;
  const currentTid = msgs.length ? msgs[msgs.length - 1].tid : undefined;
  const runningTid = st === "exec" ? currentTid : undefined;
  const elapsed = execSince ? (now - execSince) / 1000 : 0;

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
      if (["plan", "compact", "goal", "music", "memory", "skills"].includes(cmd)) {
        send({ t: "slash", cmd, arg: m[2].trim() });
        return;
      }
      toastMsg(`未知命令 /${cmd}，可用：/plan /compact /export /goal /music /memory /skills`);
      return;
    }
    // 附件提示：让 Agent 知道工作区里有哪些刚上传的文件
    const files = pendingFiles;
    const withFiles = files.length
      ? `${text}\n（工作区 uploads/ 已有刚上传的文件：${files.join("、")}）` : text;
    clearPendingFiles();
    send({ t: "text_input", text: withFiles });
  };

  /** 删除已上传文件（chips 叉号） */
  const removeFile = async (name: string) => {
    removePendingFile(name);
    fetch(`/api/files/uploaded?name=${encodeURIComponent(name)}`,
      { method: "DELETE" }).catch(() => {});
  };

  /** 文件上传（按钮 + 拖拽共用） */
  const upload = async (files: FileList | File[] | null) => {
    if (!files || !(files as any).length) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    try {
      const r = await fetch("/api/files/upload", { method: "POST", body: fd });
      const text = await r.text();
      let j: any = {};
      try { j = JSON.parse(text); } catch { /* 500 文本页 */ }
      if (!r.ok || j.error) toastMsg(`上传失败：${j.error || text.slice(0, 80) || r.status}`);
      else addPendingFiles(j.saved);
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
      {toast && <div className={"chat-toast" + (toast.slice(0, 2) !== "正在" ? " timed" : "")}>{toast}</div>}
      <div className="chat-scroll" ref={scrollRef}>
        {msgs.length === 0 && (
          <div className="chat-empty">
            <svg className="spica-star" width="32" height="32" viewBox="0 0 64 64"
  style={{ marginBottom: 12 }}>
  <path d="M32 6 C42 18 46 26 46 32 C46 38 42 46 32 58 C22 46 18 38 18 32 C18 26 22 18 32 6 Z"
    fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/>
  <path d="M32 14 C38 22 41 27 41 32 C41 37 38 42 32 50 C26 42 23 37 23 32 C23 27 26 22 32 14 Z"
    fill="var(--sand)" opacity="0.85"/>
</svg>
<div className="chat-empty-title">和 SPICA 聊聊</div>
            <div className="chat-empty-line">
              语音唤醒「Hey, SPICA」 · 点击 <MicIcon size={13} /> 直接说 · 或在下方输入
            </div>
            <div className="chat-empty-line dim">
              支持命令：/plan 只读规划 · /compact 压缩上下文 · /goal 长期目标 · /export 导出
            </div>
          </div>
        )}
        {permissionReq && (
          <div className="perm-card">
            <div className="perm-title">⚠ 申请权限：{permissionReq.perm_type || "更高权限"}</div>
            <div className="perm-reason">
              {permissionReq.action_desc || "Agent 的一次受限操作被系统拒绝。"}
            </div>
            {permissionReq.detail && (
              <details className="perm-detail">
                <summary>技术细节</summary>
                <code>{permissionReq.detail}</code>
              </details>
            )}
            <div className="perm-actions">
              <button className="btn primary" onClick={() =>
                send({ t: "permission_grant", mode: "once" })}>同意一次</button>
              <button className="btn" onClick={() =>
                send({ t: "permission_grant", mode: "always" })}>本会话永远同意</button>
              <button className="btn" onClick={() =>
                send({ t: "permission_grant", mode: "deny" })}>拒绝</button>
            </div>
            <div className="perm-voice">也可以直接说：同意 / 永远同意 / 拒绝</div>
          </div>
        )}
        {msgs.map((m, i) => {
          const tid = m.tid;
          const collapsed = tid !== undefined && turns[tid]?.collapsed;
          const isFirstOfTurn = tid !== undefined
            && !msgs.slice(0, i).some(
              (x) => x.tid === tid && x.role !== "turn-done");
          const head = tid !== undefined
            ? msgs.find((x) => x.tid === tid && x.role === "turn-done") : null;
          const showRunning = runningTid !== undefined && tid === runningTid
            && isFirstOfTurn;
          if (m.role === "turn-done") return null;
          return (
            <div key={i} id={`msg-${i}`} data-i={i}>
              {showRunning && (
                <div className="turn-running">
                  <span className="pulse-dot" />
                  运行中 · 已用时 {fmtDur(elapsed)}
                </div>
              )}
              {isFirstOfTurn && head && (
                <div className="turn-head" onClick={() => toggleTurn(tid!)}>
                  <span className="turn-caret">{collapsed ? "▸" : "▾"}</span>
                  <span className="turn-label">已完成</span>
                  <span className="turn-dur">用时 {fmtDur(head.seconds || 0)}</span>
                  {!!head.browsed && (
                    <span className="turn-web">浏览了 {head.browsed} 个网页</span>
                  )}
                </div>
              )}
              {collapsed ? (
                isFirstOfTurn && head && (
                  <>
                    {head.text && (
                      <div className="chat-msg assistant">
                        <div className="chat-role">{ROLE_LABEL.assistant}</div>
                        <div className="chat-text"><Markdown text={head.text} /></div>
                        <div className="msg-time">
                          {new Date(head.ts).toLocaleTimeString("zh-CN",
                            { hour: "2-digit", minute: "2-digit" })}
                        </div>
                      </div>
                    )}
                    {head.files && head.files.length > 0 && (
                      <FileChangeCard files={head.files} />
                    )}
                  </>
                )
              ) : m.role === "thinking" ? (
                <div className={`chat-msg thinking ${m.thinking ? "live" : ""}`}>
                  <div className="chat-role think-toggle"
                    onClick={() => setOpenThinking(
                      { ...openThinking, [i]: !openThinking[i] })}>
                    {m.thinking ? "思考中" : `思考 · ${m.text.length} 字`}
                    <span className="turn-caret">
                      {openThinking[i] ? "▾" : "▸"}</span>
                  </div>
                  {openThinking[i] && (
                    <div className="think-body">{m.text}</div>
                  )}
                </div>
              ) : (
                <div className={`chat-msg ${m.role}`}>
                  <div className="chat-role">
                    {ROLE_LABEL[m.role] || m.role}
                    {m.diff && (m.diff.a > 0 || m.diff.r > 0) && (
                      <span className="diff-badges">
                        {m.diff.a > 0 && <span className="diff-add">+{m.diff.a}</span>}
                        {m.diff.r > 0 && <span className="diff-del">-{m.diff.r}</span>}
                      </span>
                    )}
                  </div>
                  <div className="chat-text"><Markdown text={m.text} /></div>
                  {m.role === "user" && (
                    <div className="msg-time">
                      {new Date(m.ts).toLocaleTimeString("zh-CN",
                        { hour: "2-digit", minute: "2-digit" })}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
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
      {cmdOpen && (
        <div className="cmd-panel">
          {cmdMatches.map((c, i) => (
            <div key={c.cmd}
              className={"cmd-item" + (i === cmdIdx ? " active" : "")}
              onMouseEnter={() => setCmdIdx(i)}
              onClick={() => setInput("/" + c.cmd + " ")}>
              <span className="cmd-name">/{c.cmd}</span>
              <span className="cmd-hint">{c.hint}</span>
            </div>
          ))}
        </div>
      )}
      {pendingFiles.length > 0 && (
        <div className="file-chips">
          {pendingFiles.map((n) => (
            <span className="file-chip" key={n}>
              <FileIcon size={11} />{n}
              <button className="chip-x" onClick={() => removeFile(n)}>✕</button>
            </span>
          ))}
        </div>
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
          onChange={(e) => { setInput(e.target.value); setCmdIdx(0); }}
          onKeyDown={(e) => {
            if (cmdOpen) {
              if (e.key === "ArrowDown") { e.preventDefault();
                setCmdIdx((i) => (i + 1) % cmdMatches.length); return; }
              if (e.key === "ArrowUp") { e.preventDefault();
                setCmdIdx((i) => (i - 1 + cmdMatches.length) % cmdMatches.length); return; }
              if (e.key === "Tab" || (e.key === "Enter" && !input.slice(1).includes(cmdMatches[cmdIdx].cmd))) {
                e.preventDefault();
                setInput("/" + cmdMatches[cmdIdx].cmd + " ");
                return;
              }
              if (e.key === "Escape") { setInput(""); return; }
            }
            if (e.key === "Enter") submit();
          }}
          placeholder={connected
            ? "输入任务，回车发送 · / 唤起命令"
            : "未连接服务 —— 请在终端运行 make up 后自动重连"}
        />
        <button className="send-btn" onClick={submit} disabled={!connected}
          title="发送（Enter）"><SendIcon /></button>
      </div>
      <StatsBar />
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
  const st = useSpica((s) => s.state);
  const partial = useSpica((s) => s.partial);
  const route = useSpica((s) => s.route);
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
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const demo = document.documentElement.dataset.demo === "1";

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
      <Backdrop />
      <NavRail />
      <MusicBar />
      <header className="topbar">
        <div className="brand">
          <button className="shelf-btn" onClick={() => setSidebarOpen(!sidebarOpen)}
            title="会话 & 工作区">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M4 4h4v4H4zM10 4h4v4h-4zM16 4h4v4h-4zM4 10h4v4H4zM10 10h4v4h-4zM16 10h4v4h-4zM4 16h4v4H4zM10 16h4v4h-4zM16 16h4v4h-4z" />
            </svg>
          </button>
          <svg className="spica-star" width="22" height="22" viewBox="0 0 64 64">
            <path d="M32 6 C42 18 46 26 46 32 C46 38 42 46 32 58 C22 46 18 38 18 32 C18 26 22 18 32 6 Z"
              fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/>
            <path d="M32 14 C38 22 41 27 41 32 C41 37 38 42 32 50 C26 42 23 37 23 32 C23 27 26 22 32 14 Z"
              fill="var(--sand)" opacity="0.85"/>
          </svg>
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
            <ThemeToggle />
            <ModelPicker />
            {(st === "exec" || st === "paused") && (
              <button className="btn"
                onClick={() => send({ t: "command",
                  name: st === "exec" ? "pause" : "resume" })}>
                {st === "exec" ? "⏸ 暂停任务" : "▶ 继续任务"}
              </button>
            )}
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

      <div className={sidebarOpen ? "stage-body with-side" : "stage-body"}>
        <Sidebar open={sidebarOpen} />
        <div className="main-col">
          <Chat st={st} partial={partial} kbdOnly={kbdOnly}
            connected={connected} onEnableVoice={activate} />
        </div>
      </div>

      <div className={`state-dot ${wakeFlash && Date.now() - wakeFlash < 1500 ? "wake" : ""} ${st === "confirm_shutdown" ? "confirm" : ""}`} />
    </div>
  );
}
