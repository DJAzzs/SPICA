import { useEffect, useRef, useState } from "react";
import { useSpica, send } from "./state";

/** 顶部音乐卡：播放 MusicFree 流 + 智能闪避（ducking）。
 *  语音出现前 1s 渐弱至 15%，语音结束 1s 渐回；麦克风有声（用户说话）同样闪避。 */
export default function MusicBar() {
  const track = useSpica((s) => s.musicTrack);
  const stopFlag = useSpica((s) => s.musicStopFlag);
  const ttsSpeaking = useSpica((s) => s.ttsSpeaking);
  const rms = useSpica((s) => s.rms);
  const listenState = useSpica((s) => s.state) === "listen";
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(true);
  const [progress, setProgress] = useState(0);
  const [vol, setVol] = useState(0.55);
  const duckRef = useRef(1);          // 当前 duck 系数（1=正常）
  const targetRef = useRef(1);        // 目标系数
  const userVoiceRef = useRef(false); // 麦克风检测（用户说话）

  // --- 播放源切换 ---
  useEffect(() => {
    if (!track) return;
    const a = audioRef.current;
    if (!a) return;
    a.src = `/api/music/stream?id=${encodeURIComponent(track.id)}`;
    a.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  }, [track]);

  useEffect(() => {
    if (stopFlag) { audioRef.current?.pause(); }
  }, [stopFlag]);

  // --- Ducking 目标计算：TTS 或 用户说话 → 0.15 ---
  useEffect(() => {
    targetRef.current = (ttsSpeaking || userVoiceRef.current) ? 0.15 : 1;
  }, [ttsSpeaking]);

  // 用户说话检测（聆听态 rms 持续高于阈值）
  useEffect(() => {
    if (listenState && rms > 0.045) {
      userVoiceRef.current = true;
      targetRef.current = 0.15;
      clearTimeout((userVoiceRef as any)._t);
      (userVoiceRef as any)._t = setTimeout(() => {
        userVoiceRef.current = false;
        if (!ttsSpeaking) targetRef.current = 1;
      }, 1200);
    }
  }, [rms, listenState, ttsSpeaking]);

  // --- 音量斜坡：1s 渐弱/渐回（rAF 平滑） ---
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const a = audioRef.current;
      if (!a) return;
      duckRef.current += (targetRef.current - duckRef.current) * 0.035;
      a.volume = Math.max(0, Math.min(1, vol * duckRef.current));
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [vol]);

  // 进度
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onTime = () => {
      if (a.duration > 0) setProgress(a.currentTime / a.duration);
    };
    const onEnd = () => send({ t: "music_ctrl", action: "next" });
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("ended", onEnd);
    return () => { a.removeEventListener("timeupdate", onTime);
      a.removeEventListener("ended", onEnd); };
  }, []);

  if (!track) return null;
  const fmt = (s: number) =>
    `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const cur = audioRef.current?.currentTime || 0;

  return (
    <div className="music-bar">
      <audio ref={audioRef} preload="auto" />
      {track.cover ? (
        <img className="music-cover" src={`/api/music/cover?id=${encodeURIComponent(track.cover)}`}
          alt="" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />
      ) : <div className="music-cover placeholder">♪</div>}
      <div className="music-info">
        <div className="music-title">
          {track.title}
          {(ttsSpeaking || duckRef.current < 0.5) && (
            <span className="music-duck" title="语音闪避中">◌ duck</span>
          )}
        </div>
        <div className="music-artist">{track.artist} · {fmt(cur)} / {fmt(track.duration || 0)}</div>
        <div className="music-progress"><div className="music-fill"
          style={{ width: `${progress * 100}%` }} /></div>
      </div>
      <div className="music-ctrl">
        <button className="m-btn" onClick={() => {
          const a = audioRef.current!;
          if (a.paused) { a.play(); setPlaying(true); }
          else { a.pause(); setPlaying(false); }
        }}>{playing ? "❚❚" : "▶"}</button>
        <button className="m-btn" title="下一首"
          onClick={() => send({ t: "music_ctrl", action: "next" })}>⏭</button>
        <button className="m-btn" title="换一首"
          onClick={() => send({ t: "music_ctrl", action: "play", q: "" })}>⟳</button>
        <button className="m-btn" title="停止"
          onClick={() => send({ t: "music_ctrl", action: "stop" })}>✕</button>
        <input type="range" className="music-vol" min="0" max="1" step="0.02"
          value={vol} onChange={(e) => setVol(parseFloat(e.target.value))} />
      </div>
    </div>
  );
}
