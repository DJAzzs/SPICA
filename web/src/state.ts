/** WS 客户端 + 全局状态（useSyncExternalStore 模式，无重依赖）。 */
import { useSyncExternalStore } from "react";

export interface SpicaEvent { t: string; [k: string]: any }

export interface State {
  connected: boolean;
  state: string;              // idle|listen|exec|paused|confirm_shutdown|shutdown
  settings: any;
  partial: string;
  final: string;
  rewriteDraft: string;
  rewriteFinal: string;
  route: any;
  steps: { i: number; type: string; text: string; status: string }[];
  taskDone: string;
  ttsSpeaking: boolean;
  ttsText: string;
  rms: number;
  wakeFlash: number;          // 唤醒呼吸触发时间戳
  farewell: boolean;
  review: any[];
  diag: any;
  micOn: boolean;
  micError: string;
  msgs: { role: string; text: string; ts: number }[];
  localListen: boolean;   // 手动聆听本地态（不等服务器往返）
  toast: string;          // 顶部轻提示
  sessions: any[];
  currentSession: any | null;
}

const initial: State = {
  connected: false, state: "idle", settings: null,
  partial: "", final: "", rewriteDraft: "", rewriteFinal: "",
  route: null, steps: [], taskDone: "", ttsSpeaking: false, ttsText: "",
  rms: 0, wakeFlash: 0, farewell: false, review: [], diag: {},
  micOn: false, micError: "", msgs: [], localListen: false, toast: "",
  sessions: [], currentSession: null,
};

let state: State = initial;
const listeners = new Set<() => void>();

function set(patch: Partial<State>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}
export { set };
export function getState() { return state; }
export function setMic(on: boolean, error = "") {
  set({ micOn: on, micError: error });
}
/** 仅键盘模式（localStorage 持久化）。 */
export function setKbdOnly(on: boolean) {
  localStorage.setItem("spica-kbd", on ? "1" : "0");
  set({ micOn: false, micError: "" });
}

let _toastTimer: any = null;
export function toast(msg: string, ms = 4000) {
  if (_toastTimer) clearTimeout(_toastTimer);
  set({ toast: msg });
  if (ms > 0) {
    _toastTimer = setTimeout(() => set({ toast: "" }), ms);
  }
}
function subscribe(l: () => void) { listeners.add(l); return () => listeners.delete(l); }
export function useSpica<T>(sel: (s: State) => T): T {
  return useSyncExternalStore(subscribe, () => sel(state));
}

export function send(msg: object) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

/** 二进制帧（麦克风 PCM）直发。 */
export function sendBinary(buf: ArrayBuffer) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(buf);
}

let ws: WebSocket | null = null;

export function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => set({ connected: true });
  ws.onclose = () => { set({ connected: false }); setTimeout(connectWS, 1500); };
  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") handle(JSON.parse(ev.data));
    else onAudioChunk(ev.data);   // TTS PCM
  };
}

let stepSeq = 0;
function pushMsg(role: string, text: string) {
  const msg = { role, text, ts: Date.now() };
  set({ msgs: [...state.msgs.slice(-199), msg] });   // 刷新恢复的上限放大
}
function handle(e: SpicaEvent) {
  switch (e.t) {
    case "settings": set({ settings: e }); break;
    case "state":
      set({ state: e.s, farewell: e.s === "shutdown" });
      if (e.s === "listen") set({ localListen: false });   // 服务器已接手
      else if (e.s !== "idle") set({ localListen: false });
      if (e.s === "listen") set({ partial: "", final: "", rewriteDraft: "", rewriteFinal: "", steps: [] });
      break;
    case "wake_ack": set({ wakeFlash: Date.now() }); break;
    case "partial": set({ partial: e.text }); break;
    case "final":
      set({ final: e.text });   // 消息入列统一走 msg 事件（防重复）
      break;
    case "rewrite":
      if (e.stage === "draft") set({ rewriteDraft: e.text });
      else {
        set({ rewriteFinal: e.text });
        pushMsg("system", `改写 → ${e.text}`);
      }
      break;
    case "msg": pushMsg(e.role, e.text); break;
    case "route": set({ route: e }); break;
    case "step":
      stepSeq += 1;
      set({ steps: [...state.steps.slice(-7), { i: stepSeq, type: e.type, text: e.text || "", status: "active" }] });
      break;
    case "tts": set({ ttsSpeaking: e.speaking, ttsText: e.text || state.ttsText }); break;
    case "level": set({ rms: e.rms }); break;
    case "task_done":
      set({ taskDone: e.summary });
      pushMsg("assistant", e.summary);
      break;
    case "shutdown": set({ farewell: true }); break;
    case "diag": set({ diag: { ...state.diag, ...e } }); break;
    case "sessions":
      set({ sessions: e.list || [], currentSession:
        (e.list || []).find((s: any) => s.id === e.current) || null });
      break;
    case "session": set({ currentSession: e.meta }); break;
    case "history":
      set({ msgs: (e.msgs || []).map((m: any) => ({
        role: m.role, text: m.text, ts: m.ts || Date.now() })) });
      break;
    case "error": toast(`出错了：${e.message || ""}`); break;
  }
}

/* ---------------- TTS 播放（WebAudio 队列） ---------------- */
let audioCtx: AudioContext | null = null;
let playHead = 0;
let ttsSr = 24000;
let pendingChunks: Int16Array[] = [];

export function ensureAudio(): AudioContext {
  if (!audioCtx) audioCtx = new AudioContext();
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

function onAudioChunk(buf: ArrayBuffer) {
  pendingChunks.push(new Int16Array(buf));
  schedule();
}

function schedule() {
  const ctx = ensureAudio();
  if (playHead < ctx.currentTime) playHead = ctx.currentTime + 0.05;
  while (pendingChunks.length) {
    const pcm = pendingChunks.shift()!;
    const f32 = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) f32[i] = pcm[i] / 32768;
    const buf = ctx.createBuffer(1, f32.length, ttsSr);
    buf.copyToChannel(f32, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    src.start(playHead);
    playHead += buf.duration;
  }
}

/** 重置播放队列（打断/重连）。 */
export function resetPlayback() { pendingChunks = []; playHead = 0; }
