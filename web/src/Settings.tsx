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


/** 字体管理：上传 .ttf/.otf → 选择 → 开关 + 字号。 */
function FontEditor() {
  const settings = useSpica((s) => s.settings);
  const [fonts, setFonts] = useState<{name: string; size: number}[]>([]);
  const [uploading, setUploading] = useState(false);

  const loadFonts = async () => {
    try {
      const r = await fetch("/api/fonts/list");
      const j = await r.json();
      setFonts(j.fonts || []);
    } catch {}
  };
  useEffect(() => { loadFonts(); }, []);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    const fd = new FormData();
    fd.append("file", files[0]);
    try {
      await fetch("/api/fonts/upload", { method: "POST", body: fd });
      await loadFonts();
    } catch {}
    setUploading(false);
  };

  const active = settings?.custom_font || "";
  const size = settings?.custom_font_size || 0;

  // 应用/移除字体
  useEffect(() => {
    const id = "spica-custom-font";
    let el = document.getElementById(id) as HTMLStyleElement | null;
    if (active) {
      if (!el) {
        el = document.createElement("style");
        el.id = id;
        document.head.appendChild(el);
      }
      const ext = active.split(".").pop()?.toLowerCase() || "ttf";
      const fmtMap: Record<string, string> = {
        ttf: "truetype", otf: "opentype", woff: "woff", woff2: "woff2" };
      const fmt = fmtMap[ext] || "truetype";
      el.textContent = `
        @font-face {
          font-family: 'SPICA Custom';
          src: url('/api/fonts/file/${encodeURIComponent(active)}') format('${fmt}');
        }
        :root { --custom-font: 'SPICA Custom', sans-serif; }
        ${size > 0 ? `:root { font-size: ${size}px !important; }` : ""}
      `;
    } else if (el) {
      el.remove();
    }
  }, [active, size]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
        <button className="theme-toggle" onClick={() =>
          send({ t: "settings_patch",
            patch: { custom_font: active ? "" : (fonts[0]?.name || "") } })}
          title={active ? "关闭自定义字体" : "开启自定义字体"}>
          <span className={"theme-knob " + (active ? "" : "dark")}
            style={{ background: active ? "var(--mist)" : "var(--ink-faint)" }}>
            {active ? "Aa" : "—"}
          </span>
        </button>
        <span style={{ fontSize: "13px", color: "var(--ink-dim)" }}>
          {active ? `已启用：${active}` : "未启用"}
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <select value={active} onChange={e =>
          send({ t: "settings_patch",
            patch: { custom_font: e.target.value } })}
          style={{ flex: 1, font: "inherit", fontSize: "13px", padding: "8px 10px",
            borderRadius: 8, border: "1px solid var(--bg3)",
            background: "var(--bg2)", color: "var(--ink)" }}>
          <option value="">（关闭）</option>
          {fonts.map(f => (
            <option key={f.name} value={f.name}>
              {f.name}（{(f.size / 1024 / 1024).toFixed(1)}MB）
            </option>
          ))}
        </select>
        <label className="btn" style={{ cursor: "pointer" }}>
          {uploading ? "上传中…" : "＋ 上传字体"}
          <input type="file" accept=".ttf,.otf,.woff,.woff2"
            onChange={e => upload(e.target.files)}
            style={{ display: "none" }} />
        </label>
      </div>

      {active && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: "12px", color: "var(--ink-faint)" }}>字号</span>
          <input type="range" min={12} max={20} step={1}
            value={size || 16}
            onChange={e => send({ t: "settings_patch",
              patch: { custom_font_size: parseInt(e.target.value) } })}
            style={{ flex: 1, accentColor: "var(--mist)" }} />
          <span style={{ fontSize: "13px", color: "var(--ink-dim)",
            fontVariantNumeric: "tabular-nums", minWidth: 32 }}>
            {size || 16}px
          </span>
        </div>
      )}
      <div className="hint" style={{ marginTop: 8 }}>
        下载 .ttf/.otf 字体文件（如霞鹜文楷、得意黑、JetBrains Mono），上传后选择即可全局生效。
      </div>
    </div>
  );
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
          <label>字体</label>
          <FontEditor />
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
