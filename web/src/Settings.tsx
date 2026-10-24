import { useState } from "react";
import { useSpica, send } from "./state";

/** 设置页：词表/阈值/路由/音色/主题/演示模式。 */
export default function Settings() {
  const settings = useSpica((s) => s.settings);
  const [wakeInput, setWakeInput] = useState("");
  const [threshold, setThreshold] = useState<string>(
    String(settings?.speaker_threshold ?? 0.55));

  if (!settings) return <div className="panel"><div className="inner"><h1>设置</h1><div className="hint">连接中…</div></div></div>;

  return (
    <div className="panel">
      <div className="inner">
        <h1>设置</h1>

        <div className="field">
          <label>唤醒词（每行一条：主词 | 变体1,变体2…）</label>
          <textarea value={(settings.wake_words || [])
            .map((w: any) => `${w.phrase} | ${(w.variants || []).join(",")}`).join("\n")}
            onChange={(e) => {
              const words = e.target.value.split("\n").filter(Boolean).map((line) => {
                const [phrase, variants] = line.split("|").map((s) => s.trim());
                return { phrase, variants: (variants || "").split(",").map((v) => v.trim()).filter(Boolean), enabled: true };
              });
              send({ t: "settings_patch", patch: { wake_words: words } });
            }} />
        </div>

        <div className="field">
          <label>结束词</label>
          <textarea value={(settings.farewell_words || [])
            .map((w: any) => `${w.phrase} | ${(w.variants || []).join(",")}`).join("\n")}
            onChange={(e) => {
              const words = e.target.value.split("\n").filter(Boolean).map((line) => {
                const [phrase, variants] = line.split("|").map((s) => s.trim());
                return { phrase, variants: (variants || "").split(",").map((v) => v.trim()).filter(Boolean), enabled: true };
              });
              send({ t: "settings_patch", patch: { farewell_words: words } });
            }} />
        </div>

        <div className="field">
          <label>声纹阈值（当前 {settings.speaker_threshold}，越小越宽松）</label>
          <input type="text" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          <button className="btn" style={{ marginTop: 8 }} onClick={() =>
            send({ t: "settings_patch", patch: { speaker_threshold: parseFloat(threshold) || 0.55 } })
          }>保存阈值</button>
        </div>

        <div className="field">
          <label>音色预设</label>
          <select defaultValue={settings.tts_voice_preset || "清朗助理"}
            onChange={(e) => send({ t: "settings_patch", patch: { tts_voice_preset: e.target.value } })}>
            {["清朗助理", "沉稳管家", "少年灵音"].map((v) => <option key={v}>{v}</option>)}
          </select>
        </div>

        <div className="field">
          <label>外观</label>
          <div className="btn-row">
            <button className="btn" onClick={() => {
              const t = document.documentElement.dataset.theme === "light" ? "dark" : "light";
              document.documentElement.dataset.theme = t;
              localStorage.setItem("spica-theme", t);
            }}>亮 / 暗切换</button>
            <button className="btn" onClick={() => {
              document.documentElement.dataset.demo = "1";
            }}>进入演示模式（Esc Esc 退出）</button>
          </div>
        </div>

        <div className="btn-row"><a className="btn" href="#/">返回</a></div>
      </div>
    </div>
  );
}
