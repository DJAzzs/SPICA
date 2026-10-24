/** 麦克风采集：getUserMedia(AEC/NS/AGC) → AudioWorklet → 16kHz int16 → WS 二进制。
 * Worklet 代码以 Blob URL 注入（免静态文件路径）。48k/96k→16k 整数倍抽取。
 */
import { sendBinary } from "./state";

const WORKLET_CODE = `
class SpicaRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this._carry = 0;   // 跨块相位余数
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    const step = Math.round(sampleRate / 16000);
    const out = [];
    for (let i = this._carry; i < ch.length; i += step) out.push(ch[i]);
    this._carry = (this._carry + ch.length) % step;
    const pcm = new Int16Array(out.length);
    for (let i = 0; i < out.length; i++) {
      const v = Math.max(-1, Math.min(1, out[i]));
      pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
    this.port.postMessage(pcm.buffer, [pcm.buffer]);
    return true;
  }
}
registerProcessor("spica-recorder", SpicaRecorder);
`;

let stream: MediaStream | null = null;
let node: AudioWorkletNode | null = null;
let ctx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let waveBuf: Uint8Array<ArrayBuffer> | null = null;

function ensureWaveBuf(size: number): Uint8Array<ArrayBuffer> {
  if (!waveBuf || waveBuf.length !== size) {
    waveBuf = new Uint8Array(new ArrayBuffer(size));
  }
  return waveBuf;
}

export async function startMic(deviceId?: string): Promise<MediaTrackSettings> {
  stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      deviceId: deviceId ? { exact: deviceId } : undefined,
      echoCancellation: true,     // 浏览器 AEC：防 TTS 自唤醒（关键）
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    },
  });
  const track = stream.getAudioTracks()[0];
  ctx = new AudioContext({ sampleRate: 48000 });
  const url = URL.createObjectURL(new Blob([WORKLET_CODE], { type: "text/javascript" }));
  await ctx.audioWorklet.addModule(url);
  URL.revokeObjectURL(url);
  const src = ctx.createMediaStreamSource(stream);
  // 本地可视化分析器（rAF 帧率，零网络往返）
  analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  src.connect(analyser);
  node = new AudioWorkletNode(ctx, "spica-recorder");
  node.port.onmessage = (ev) => sendBinary(ev.data as ArrayBuffer);
  src.connect(node);
  return track.getSettings();
}

/** 实时波形（time-domain，0-255）。未开启麦克风时返回 null。 */
export function readWaveform(): Uint8Array<ArrayBuffer> | null {
  if (!analyser) return null;
  const buf = ensureWaveBuf(analyser.fftSize);
  analyser.getByteTimeDomainData(buf);
  return buf;
}

/** 本地麦克风 RMS（0~1 附近），可视化/场景律动用。 */
export function getMicLevel(): number {
  const w = readWaveform();
  if (!w) return 0;
  let s = 0;
  for (let i = 0; i < w.length; i += 4) {
    const d = (w[i] - 128) / 128;
    s += d * d;
  }
  return Math.sqrt(s / (w.length / 4));
}

export function stopMic() {
  node?.disconnect(); node = null;
  stream?.getTracks().forEach((t) => t.stop()); stream = null;
  ctx?.close(); ctx = null;
}

/** 设备枚举（诊断页/向导）。 */
export async function listDevices(): Promise<{ mics: MediaDeviceInfo[]; cams: MediaDeviceInfo[] }> {
  const all = await navigator.mediaDevices.enumerateDevices();
  return {
    mics: all.filter((d) => d.kind === "audioinput"),
    cams: all.filter((d) => d.kind === "videoinput"),
  };
}
