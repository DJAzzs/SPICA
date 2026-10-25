import { useEffect, useState } from "react";
import { useSpica, send } from "./state";

/** 模型服务商配置：API 地址 / Key / 改写模型 / 自定义模型列表（热生效）。 */
function ProviderEditor() {
  const settings = useSpica((s) => s.settings);
  const [baseUrl, setBaseUrl] = useState(settings?.llm_base_url || "");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(settings?.llm_model_rewrite || "");
  const [custom, setCustom] = useState(settings?.custom_models || "");
  return (
    <>
      <input type="text" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
        placeholder="API 地址（如 https://open.bigmodel.cn/api/coding/paas/v4）" />
      <input type="text" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
        placeholder={settings?.has_key ? "API Key（已配置，留空不修改）" : "API Key"}
        style={{ marginTop: 10 }} />
      <input type="text" value={model} onChange={(e) => setModel(e.target.value)}
        placeholder="改写/路由模型（如 glm-5.3-flash）" style={{ marginTop: 10 }} />
      <input type="text" value={custom} onChange={(e) => setCustom(e.target.value)}
        placeholder="自定义模型列表，逗号分隔（如 deepseek-chat, glm-5.3-air）"
        style={{ marginTop: 10 }} />
      <div className="btn-row">
        <button className="btn" onClick={() => {
          const patch: any = {
            llm_base_url: baseUrl.trim(),
            llm_model_rewrite: model.trim(),
            custom_models: custom.trim(),
          };
          if (apiKey.trim()) patch.llm_api_key = apiKey.trim();
          send({ t: "settings_patch", patch });
        }}>保存服务配置</button>
      </div>
    </>
  );
}

/** 声纹门控开关（新拟物/玻璃滑块）。 */
function SpeakerGateToggle() {
  const settings = useSpica((s) => s.settings);
  const on = settings?.speaker_gate_enabled !== false;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <button className="theme-toggle" onClick={() =>
        send({ t: "settings_patch",
          patch: { speaker_gate_enabled: !on } })}
        title={on ? "点击关闭声纹验证" : "点击开启声纹验证"}>
        <span className={"theme-knob " + (on ? "" : "dark")}
          style={{ background: on ? "var(--mist)" : "var(--ink-faint)" }}>
          {on
            ? <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                stroke="#fff" strokeWidth="2" strokeLinecap="round">
                <path d="M9 12l2 2 4-4" /><circle cx="12" cy="12" r="10" />
              </svg>
            : <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                stroke="#fff" strokeWidth="2" strokeLinecap="round">
                <circle cx="12" cy="12" r="10" /><path d="M6 6l12 12" />
              </svg>}
        </span>
      </button>
      <span style={{ fontSize: "12.5px", color: "var(--ink-dim)" }}>
        {on ? "已开启：只回应你的声音（他人静默）" : "已关闭：任何人都能唤醒"}
      </span>
    </div>
  );
}

/** 词列 chips：只展示主词，变体后台自动生成。 */
function WordChips({ initial, field }: { initial: any[]; field: string }) {
  const [adding, setAdding] = useState(false);
  const [newWord, setNewWord] = useState("");

  const addWord = () => {
    const w = newWord.trim();
    if (!w) return;
    const words = [...(initial || []),
      { phrase: w, variants: [], enabled: true }];
    send({ t: "settings_patch", patch: { [field]: words } });
    setNewWord(""); setAdding(false);
  };

  const removeWord = (phrase: string) => {
    const words = (initial || []).filter((w: any) => w.phrase !== phrase);
    send({ t: "settings_patch", patch: { [field]: words } });
  };

  const toggleWord = (phrase: string) => {
    const words = (initial || []).map((w: any) =>
      w.phrase === phrase ? { ...w, enabled: !w.enabled } : w);
    send({ t: "settings_patch", patch: { [field]: words } });
  };

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {(initial || []).map((w: any) => (
        <span key={w.phrase}
          className={"word-chip" + (w.enabled === false ? " off" : "")}>
          <span className="word-text" onClick={() => toggleWord(w.phrase)}>
            {w.phrase}
          </span>
          <button className="chip-x" onClick={() => removeWord(w.phrase)}>✕</button>
        </span>
      ))}
      {adding ? (
        <span className="word-chip adding">
          <input type="text" value={newWord}
            onChange={e => setNewWord(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") addWord();
              if (e.key === "Escape") { setAdding(false); setNewWord(""); } }}
            placeholder="输入新词…" autoFocus
            style={{ width: 100, border: "none", background: "none",
              outline: "none", color: "var(--ink)", font: "inherit",
              fontSize: "12px" }} />
          <button className="chip-x" onClick={addWord} style={{ color: "var(--mist)" }}>✓</button>
        </span>
      ) : (
        <button className="word-chip add" onClick={() => setAdding(true)}>＋</button>
      )}
    </div>
  );
}

/** 词表编辑器：本地缓冲，blur 时提交（防光标跳变）。 */
function WordEditor({ initial, field }: { initial: any[]; field: string }) {
  const [text, setText] = useState(
    (initial || []).map((w: any) =>
      `${w.phrase} | ${(w.variants || []).join(",")}`).join("\n"));
  const commit = () => {
    const words = text.split("\n").filter(Boolean).map((line: string) => {
      const [phrase, variants] = line.split("|").map((s) => s.trim());
      return { phrase, variants: (variants || "").split(",")
        .map((v: string) => v.trim()).filter(Boolean), enabled: true };
    });
    send({ t: "settings_patch", patch: { [field]: words } });
  };
  return <textarea value={text}
    onChange={(e) => setText(e.target.value)}
    onBlur={commit} />;
}


/** 身份编辑器：内置身份只读展示；开关开启后可完全覆盖。 */
function IdentityEditor() {
  const settings = useSpica((s) => s.settings);
  const builtin: string = settings?.spica_identity || "（连接后显示内置身份）";
  const [override, setOverride] = useState(settings?.identity_override || "");
  const on = (settings?.identity_override || "") !== "";
  return (
    <>
      <div className="hint" style={{ marginBottom: 8 }}>
        内置身份（{on ? "已被覆盖" : "生效中"}，闲聊回复与任务均以此自我认知）：
      </div>
      <textarea value={on ? override : builtin} readOnly={!on}
        onChange={(e) => setOverride(e.target.value)}
        style={{ opacity: on ? 1 : 0.75, minHeight: 130 }} />
      <div className="btn-row" style={{ marginTop: 12 }}>
        <button className="btn" onClick={() =>
          send({ t: "settings_patch", patch: {
            identity_override: on ? "" : builtin } })}>
          {on ? "恢复内置身份" : "覆盖内置身份（可编辑）"}
        </button>
        {on && (
          <button className="btn primary" onClick={() =>
            send({ t: "settings_patch", patch: {
              identity_override: override } })}>保存覆盖</button>
        )}
      </div>
      <div className="hint">覆盖后内置身份不再使用；下方“人设”始终追加生效。</div>
    </>
  );
}

/** 人设编辑器：SystemPrompt/角色设定，任务级注入。 */
function PersonaEditor() {
  const settings = useSpica((s) => s.settings);
  const [text, setText] = useState(settings?.persona || "");
  return (
    <>
      <textarea value={text} onChange={(e) => setText(e.target.value)}
        placeholder={"例如：你是一位严谨的资深架构师，回答精炼、给结论先给依据；"
          + "代码风格偏函数式；对我使用「老板」称呼。"} />
      <div className="btn-row">
        <button className="btn" onClick={() =>
          send({ t: "settings_patch", patch: { persona: text.trim() } })
        }>保存人设</button>
      </div>
    </>
  );
}

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
          <label>唤醒词</label>
          <WordChips initial={settings.wake_words} field="wake_words" />
        </div>

        <div className="field">
          <label>结束词</label>
          <WordChips initial={settings.farewell_words} field="farewell_words" />
        </div>

        <div className="field">
          <label>声纹门控</label>
          <SpeakerGateToggle />
        </div>

        <div className="field">
          <label>声纹阈值（当前 {settings.speaker_threshold}，越小越宽松）</label>
          <input type="text" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          <button className="btn" style={{ marginTop: 8 }} onClick={() =>
            send({ t: "settings_patch", patch: { speaker_threshold: parseFloat(threshold) || 0.55 } })
          }>保存阈值</button>
        </div>

        <div className="field">
          <label>模型服务（SPICA 改写/路由/播报压缩使用的 API）</label>
          <ProviderEditor />
          <div className="hint">
            OpenAI 兼容端点。执行任务的模型在顶栏下拉选择；自定义模型列表会出现在该下拉中。
          </div>
        </div>

        <div className="field">
          <label>身份与人设</label>
          <IdentityEditor />
          <div style={{ marginTop: 16 }}><PersonaEditor /></div>
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
