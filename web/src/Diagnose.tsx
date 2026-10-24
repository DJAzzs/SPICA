import { useEffect, useRef, useState } from "react";
import { listDevices } from "./audio";

/** 硬件诊断：麦克风枚举/电平/试录（通过服务端 level 事件），摄像头探针。 */
export default function Diagnose() {
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [cams, setCams] = useState<MediaDeviceInfo[]>([]);
  const [camOk, setCamOk] = useState<null | boolean>(null);
  const [micStatus, setMicStatus] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    listDevices().then(({ mics, cams }) => { setMics(mics); setCams(cams); });
  }, []);

  const probeCam = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: true });
      if (videoRef.current) {
        videoRef.current.srcObject = s;
        await videoRef.current.play();
      }
      setCamOk(true);
      s.getTracks().forEach((t) => t.stop()); // 探测即关（M2 再常开）
      if (videoRef.current) videoRef.current.srcObject = null;
    } catch {
      setCamOk(false);
    }
  };

  return (
    <div className="panel">
      <div className="inner">
        <h1>硬件诊断</h1>

        <div className="field">
          <label>麦克风（{mics.length} 个）</label>
          {mics.map((m) => (
            <div key={m.deviceId} className="review-item">{m.label || m.deviceId.slice(0, 16)}</div>
          ))}
          <div className="hint">{micStatus}</div>
          <div className="btn-row">
            <button className="btn" onClick={async () => {
              try {
                const { startMic } = await import("./audio");
                const st = await startMic();
                setMicStatus(`采集中 @${st.sampleRate}Hz · 电平看主界面声纹线`);
              } catch (e) {
                setMicStatus(`失败：${e}`);
              }
            }}>开始采集</button>
          </div>
        </div>

        <div className="field">
          <label>摄像头（{cams.length} 个）{camOk === true && <span className="status-ok"> · 可用</span>}
            {camOk === false && <span className="status-fail"> · 不可用</span>}</label>
          <button className="btn" onClick={probeCam}>探测</button>
          <video ref={videoRef} style={{ width: "100%", marginTop: 16, display: "none" }} muted playsInline />
          <div className="hint">M2 手部追踪需要摄像头；探测即开即关。</div>
        </div>

        <div className="btn-row"><a className="btn" href="#/">返回</a></div>
      </div>
    </div>
  );
}
