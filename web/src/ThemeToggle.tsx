import { useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "./icons";

export type ThemeMode = "auto" | "light" | "dark";

function resolve(mode: ThemeMode): "light" | "dark" {
  if (mode !== "auto") return mode;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** 应用主题并广播（单一事实源：document.dataset.theme + 事件刷新）。 */
export function applyTheme(mode: ThemeMode) {
  localStorage.setItem("spica-theme-mode", mode);
  document.documentElement.dataset.theme = resolve(mode);
  dispatchEvent(new Event("spica-theme"));
}

/** 三态主题开关：默认跟随系统；点击滑块锁定深/浅；AUTO 交还系统。 */
export default function ThemeToggle() {
  // 以 spica-theme 事件驱动重渲染（applyTheme / 系统切换都会触发）
  const [, setTick] = useState(0);
  useEffect(() => {
    const on = () => setTick((t) => t + 1);
    addEventListener("spica-theme", on);
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onSys = () => {
      const m = (localStorage.getItem("spica-theme-mode") as ThemeMode) || "auto";
      if (m === "auto") applyTheme("auto");   // 广播刷新（幂等）
    };
    mq.addEventListener("change", onSys);
    return () => {
      removeEventListener("spica-theme", on);
      mq.removeEventListener("change", onSys);
    };
  }, []);

  const mode: ThemeMode =
    (localStorage.getItem("spica-theme-mode") as ThemeMode) || "auto";
  const isDark = document.documentElement.dataset.theme === "dark";

  return (
    <div className="theme-wrap">
      <button className="theme-toggle"
        onClick={() => applyTheme(isDark ? "light" : "dark")}
        title={isDark ? "切换到浅色" : "切换到深色"} aria-label="主题切换">
        <span className={`theme-knob ${isDark ? "dark" : ""}`}>
          {isDark ? <MoonIcon /> : <SunIcon />}
        </span>
      </button>
      <button className={`theme-auto ${mode === "auto" ? "on" : ""}`}
        onClick={() => applyTheme("auto")}
        title="跟随系统主题">AUTO</button>
    </div>
  );
}
