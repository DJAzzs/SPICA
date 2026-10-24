import { useEffect, useState } from "react";
import { useSpica, send } from "./state";
import Wave from "./Wave";

const STEPS = ["硬件", "唤醒词", "声纹", "音色", "结束"];

/** 声纹注册步骤：纯视觉引导（注册期零 TTS，防自采），波形+实时转写+计数。 */
function EnrollStep() {
  const diag = useSpica((s) => s.diag);
  const partial = useSpica((s) => s.partial);
  const enroll: any = diag.enroll || {};
  const got: number = enroll.got ?? 0;
  const target: number = enroll.target ?? 3;
  const phase = enroll.phase;

  return (
    <div className="field">
      <label>声纹注册（注册完成后 SPICA 只回应你的声音）</label>

      {phase !== "done" && (
        <>
          <div className="enroll-progress">
            {Array.from({ length: target }).map((_, i) => (
              <span key={i} className={`enroll-dot ${i < got ? "on" : ""}`} />
            ))}
            <span className="enroll-count">{got} / {target}</span>
          </div>
          <Wave height={72} />
          <div className="hint">
            {phase === "too_short"
              ? "刚才那段太短了，再说一句长一点的"
              : phase === "start" || phase === undefined
                ? "点击下方开始，然后自然地说一句话（比如说说今天打算做什么）"
                : phase === "progress"
                  ? "很好，继续说下一句"
                  : "正在采集…"}
          </div>
          {partial && <div className="enroll-live">{partial}</div>}
          <div className="btn-row">
            {phase === undefined || phase === "abort" ? (
              <button className="btn primary" onClick={() =>
                send({ t: "enroll_start", n: 3 })}>开始注册</button>
            ) : (
              <button className="btn" onClick={() => send({ t: "enroll_abort" })}>
                重新开始
              </button>
            )}
          </div>
        </>
      )}

      {phase === "done" && (
        <div className={`hint ${enroll.ok ? "status-ok" : "status-fail"}`}>
          {enroll.ok
            ? "注册完成。现在可以试试：让家人对它喊唤醒词，它应该保持沉默。"
            : "注册失败（样本不足或太安静），点击重新开始再试。"}
          <div className="btn-row">
            <button className="btn" onClick={() => send({ t: "enroll_abort" })}>
              重新注册
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** 音色步骤：预设 + 自定义描述（提示词）+ 试听。 */
function VoiceStep() {
  const settings = useSpica((s) => s.settings);
  const [preset, setPreset] = useState(settings?.tts_voice_preset || "清朗助理");
  const [desc, setDesc] = useState(settings?.tts_custom_description || "");
  const [previewText, setPreviewText] = useState(
    "你好，我是 SPICA。这是音色试听，希望你喜欢这个声音。");
  const [busy, setBusy] = useState(false);

  const apply = (extra: object = {}) => ({
    tts_voice_preset: preset,
    tts_custom_description: desc.trim(),
    ...extra,
  });

  return (
    <div className="field">
      <label>音色</label>
      <select value={preset} onChange={(e) => setPreset(e.target.value)}>
        {["清朗助理", "沉稳管家", "少年灵音"].map((v) => (
          <option key={v} value={v}>{v}</option>
        ))}
      </select>
      <label style={{ marginTop: 16 }}>自定义音色描述（提示词，留空则用预设）</label>
      <textarea value={desc} onChange={(e) => setDesc(e.target.value)}
        placeholder="例如：一位温和的青年女性声音，语速平缓，带一点书卷气，尾音轻柔" />
      <label style={{ marginTop: 16 }}>试听文本</label>
      <input type="text" value={previewText} onChange={(e) => setPreviewText(e.target.value)} />
      <div className="btn-row">
        <button className="btn" disabled={busy} onClick={async () => {
          setBusy(true);
          try {
            await fetch("/api/settings", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(apply({ tts_preview_text: previewText })),
            });
          } finally { setTimeout(() => setBusy(false), 4000); }
        }}>{busy ? "合成中…" : "试听"}</button>
        <button className="btn primary" onClick={() =>
          send({ t: "settings_patch", patch: apply() })}>保存音色</button>
      </div>
      <div className="hint">描述会交给 Qwen3-TTS VoiceDesign 渲染；保存后立即生效（热更新，无需重启）。</div>
    </div>
  );
}

export default function Wizard() {
  const [step, setStep] = useState(0);
  const settings = useSpica((s) => s.settings);
  const [wakeText, setWakeText] = useState("Hey, SPICA 帮我看看今天天气");
  const [wakeResult, setWakeResult] = useState<any>(null);

  // 诊断事件的唤醒测试回填
  const diag = useSpica((s) => s.diag);
  useEffect(() => {
    if (diag.wake_test !== undefined) setWakeResult(diag);
  }, [diag]);

  return (
    <div className="panel">
      <div className="inner" style={{ width: 640 }}>
        <h1>首启向导 · {STEPS[step]}（{step + 1}/{STEPS.length}）</h1>

        {step === 0 && (
          <div className="field">
            <label>第一步：确认硬件</label>
            <div className="hint">
              先到 <a href="#/diagnose" style={{ color: "var(--accent)" }}>诊断页</a>{" "}
              确认麦克风可用（WL24A），主界面声纹线随说话起伏即正常。
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="field">
            <label>第二步：唤醒词校准（可对着麦克风说，或模拟匹配）</label>
            <input type="text" value={wakeText} onChange={(e) => setWakeText(e.target.value)} />
            <div className="btn-row">
              <button className="btn" onClick={() =>
                send({ t: "wake_test", text: wakeText })}>模拟匹配</button>
            </div>
            {wakeResult && (
              <div className={`hint ${wakeResult.wake_test ? "status-ok" : "status-fail"}`}>
                {wakeResult.wake_test
                  ? `命中：${wakeResult.matched}${wakeResult.farewell ? "（注意：同时命中结束词！）" : ""}`
                  : "未命中——可在设置里增加变体"}
              </div>
            )}
            <div className="hint">
              当前词表：{settings?.wake_words?.map((w: any) => w.phrase).join(" / ")}
              {"　"}结束词：{settings?.farewell_words?.map((w: any) => w.phrase).join(" / ")}
            </div>
          </div>
        )}

        {step === 2 && <EnrollStep />}

        {step === 3 && <VoiceStep />}

        {step === 4 && (
          <div className="field">
            <label>完成</label>
            <div className="hint">
              一切就绪。回到主界面说「Hey, SPICA」或直接打字开始。
              「Bye, SPICA」随时存档关停。
            </div>
            <div className="btn-row">
              <button className="btn primary" onClick={() => {
                send({ t: "settings_patch", patch: { wizard_done: true } });
                location.hash = "#/";
              }}>完成向导</button>
            </div>
          </div>
        )}

        <div className="btn-row">
          {step > 0 && <button className="btn" onClick={() => setStep(step - 1)}>上一步</button>}
          {step < STEPS.length - 1 && <button className="btn primary" onClick={() => setStep(step + 1)}>下一步</button>}
          <a className="btn" href="#/">返回主界面</a>
        </div>
      </div>
    </div>
  );
}
