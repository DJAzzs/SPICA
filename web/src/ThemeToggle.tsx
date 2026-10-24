import { MoonIcon, SunIcon } from "./icons";
import { useEffect, useState } from "react";

export type ThemeMode = "auto" | "light" | "dark";

function resolve(mode: ThemeMode): "light" | "dark" {
  if (mode !== "auto") return mode;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(mode: ThemeMode) {
  localStorage.setItem("spica-theme-mode", mode);
  document.documentElement.dataset.theme = resolve(mode);
  dispatchEvent(new Event("spica-theme"));
}

/** 三态主题：默认跟随系统；点击滑块手动锁定深/浅；AUTO 回跟随。 */
export default function ThemeToggle() {
  const [mode, setMode] = useState<ThemeMode>(
    () => (localStorage.getItem("spica-theme-mode") as ThemeMode) || "auto");
  const isDark = resolve(mode) === "dark";

  useEffect(() => {
    document.documentElement.dataset.theme = resolve(mode);
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (mode === "auto") {
        document.documentElement.dataset.theme = resolve("auto");
        dispatchEvent(new Event("spica-theme"));
      }
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [mode]);

  return (
    <div className="theme-wrap">
      <button className="theme-toggle" onClick={() => applyTheme(isDark ? "light" : "dark")}
        title={isDark ? "切换到浅色" : "切换到深色"} aria-label="主题切换">
        <span className={`theme-knob ${isDark ? "dark" : ""}`}>
          {isDark ? <MoonIcon /> : <SunIcon />}
        </span>
      </button>
      <button className={`theme-auto ${mode === "auto" ? "on" : ""}`}
        onClick={() => { applyTheme("auto"); setMode("auto"); }}
        title="跟随系统主题">AUTO</button>
    </div>
  );
}
