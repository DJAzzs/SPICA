import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import App from "./App";
import Diagnose from "./Diagnose";
import Wizard from "./Wizard";
import SettingsPage from "./Settings";
import Review from "./Review";
import Sessions from "./Sessions";
import Files from "./Files";
import { connectWS } from "./state";

function Router() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const on = () => setHash(location.hash);
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);

  // 主题持久化
  useEffect(() => {
    const saved = localStorage.getItem("spica-theme") || "dark";
    document.documentElement.dataset.theme = saved;
  }, []);

  // 演示模式：Esc Esc 退出
  useEffect(() => {
    let last = 0;
    const on = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (Date.now() - last < 600) {
          delete document.documentElement.dataset.demo;
        }
        last = Date.now();
      }
    };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  }, []);

  switch (hash) {
    case "#/diagnose": return <Diagnose />;
    case "#/wizard": return <Wizard />;
    case "#/settings": return <SettingsPage />;
    case "#/review": return <Review />;
    case "#/sessions": return <Sessions />;
    case "#/files": return <Files />;
    default: return <App />;
  }
}

connectWS();
createRoot(document.getElementById("root")!).render(<Router />);
