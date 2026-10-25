import { useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "./icons";

export type ThemeMode = "auto" | "light" | "dark";

function resolve(mode: ThemeMode): "light" | "dark" {
  if (mode !== "auto") return mode;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

let _animTimer: any = null;
export function applyTheme(mode: ThemeMode) {
  localStorage.setItem("spica-theme-mode", mode);
  const root = document.documentElement;
  root.classList.add("theme-anim");
  if (_animTimer) clearTimeout(_animTimer);
  _animTimer = setTimeout(() => root.classList.remove("theme-anim"), 850);
  root.dataset.theme = resolve(mode);
  dispatchEvent(new Event("spica-theme"));
}

export default function ThemeToggle() {
  const [, setTick] = useState(0);
  useEffect(() => {
    const on = () => setTick((t) => t + 1);
    addEventListener("spica-theme", on);
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onSys = () => {
      const m = (localStorage.getItem("spica-theme-mode") as ThemeMode) || "auto";
      if (m === "auto") applyTheme("auto");
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
