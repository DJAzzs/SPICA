import { useState } from "react";
import { useSpica, send } from "./state";

/** 自定义音色描述编辑器：提示词 + 试听（热更新）。 */
function VoiceDescEditor() {
  const settings = useSpica((s) => s.settings);
  const [desc, setDesc] = useState(settings?.tts_custom_description || "");
  const [busy, setBusy] = useState(false);
  return (
    <>
      <textarea value={desc} onChange={(e) => setDesc(e.target.value)}
        placeholder="例如：一位温和的青年女性声音，语速平缓，带一点书卷气" />
      <div className="btn-row">
        <button className="btn" disabled={busy} onClick={async () => {
          setBusy(true);
          try {
            await fetch("/api/settings", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                tts_custom_description: desc.trim(),
                tts_preview_text: "你好，我是 SPICA，这是当前音色。",
              }),
            });
          } finally { setTimeout(() => setBusy(false), 4000); }
        }}>{busy ? "合成中…" : "保存并试听"}</button>
      </div>
    </>
  );
}

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
          <label style={{ marginTop: 16 }}>自定义音色描述（提示词，留空用预设）</label>
          <VoiceDescEditor />
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
            <button className="btn" onClick={() => {
              send({ t: "settings_patch", patch: { wizard_done: false } });
              location.hash = "#/wizard";
            }}>重新运行向导</button>
          </div>
        </div>

        <div className="btn-row"><a className="btn" href="#/">返回</a></div>
      </div>
    </div>
  );
}
