import { useEffect, useState } from "react";
import { useSpica, send } from "./state";

const STEPS = ["硬件", "唤醒词", "声纹", "音色", "结束词"];

/** 首启向导：硬件→唤醒词校准→声纹注册→音色试听→结束词+告别包。 */
export default function Wizard() {
  const [step, setStep] = useState(0);
  const settings = useSpica((s) => s.settings);
  const [wakeText, setWakeText] = useState("Hey, SPICA 帮我看看今天天气");
  const [wakeResult, setWakeResult] = useState<any>(null);
  const [voiceText, setVoiceText] = useState("SPICA 语音系统已就绪，随时待命。");

  useEffect(() => { send({ t: "review_get" }); }, [step]);

  return (
    <div className="panel">
      <div className="inner">
        <h1>首启向导 · {STEPS[step]}（{step + 1}/{STEPS.length}）</h1>

        {step === 0 && (
          <div className="field">
            <label>第一步：确认硬件</label>
            <div className="hint">请先到 <a href="#/diagnose" style={{ color: "var(--accent)" }}>诊断页</a> 确认麦克风可用并开始采集，然后回到这里。</div>
          </div>
        )}

        {step === 1 && (
          <div className="field">
            <label>第二步：唤醒词校准（对着麦克风说一句）</label>
            <input type="text" value={wakeText} onChange={(e) => setWakeText(e.target.value)} />
            <div className="btn-row">
              <button className="btn" onClick={async () => {
                send({ t: "wake_test", text: wakeText });
              }}>模拟匹配</button>
            </div>
            {wakeResult && (
              <div className={`hint ${wakeResult.wake_test ? "status-ok" : "status-fail"}`}>
                {wakeResult.wake_test
                  ? `命中：${wakeResult.matched}${wakeResult.farewell ? "（注意：同时命中结束词！）" : ""}`
                  : "未命中——请检查词表或变体"}
              </div>
            )}
            <div className="hint">当前词表：{settings?.wake_words?.map((w: any) => w.phrase).join(" / ")}
              {"  "}结束词：{settings?.farewell_words?.map((w: any) => w.phrase).join(" / ")}</div>
          </div>
        )}

        {step === 2 && (
          <div className="field">
            <label>第三步：声纹注册（自然说 3 句话）</label>
            <div className="hint">点击开始后正常说话；注册后 SPICA 只回应你的声音。</div>
            <div className="btn-row">
              <button className="btn primary" onClick={() => {
                send({ t: "enroll_start", n: 3 });
              }}>开始注册</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="field">
            <label>第四步：音色试听</label>
            <select onChange={(e) => {
              send({ t: "settings_patch", patch: { tts_voice_preset: e.target.value } });
            }} defaultValue={settings?.tts_voice_preset || "清朗助理"}>
              {["清朗助理", "沉稳管家", "少年灵音"].map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
            <input type="text" value={voiceText} onChange={(e) => setVoiceText(e.target.value)}
              style={{ marginTop: 12 }} />
            <div className="hint">试听即由服务端合成并推送播放（首次需加载模型，稍候）。</div>
            <div className="btn-row">
              <button className="btn" onClick={() => {
                fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ tts_preview_text: voiceText }) });
              }}>试听</button>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="field">
            <label>第五步：完成</label>
            <div className="hint">
              唤醒词与结束词已就绪（设置页可增删变体）；应答语音包已在后台预生成。
              现在回到主界面说「Hey, SPICA」试试。
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
