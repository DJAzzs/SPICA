import { useState } from "react";
import { useSpica } from "./state";

/** 网页浏览折叠卡 — 与思考块同款交互。 */
export default function WebCard() {
  const [cards, setCards] = useState<{host: string; url: string}[]>([]);
  const [open, setOpen] = useState<Record<number, boolean>>({});

  useSpica((s) => {
    // 监听新 web_card 事件（由 state.ts 处理后存入）
  });

  return null; // 由 App.tsx 内联渲染
}

export function WebCardItem({ host, url, tid }: {
  host: string; url: string; tid: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="web-card" onClick={() => setOpen(!open)}>
      <div className="wc-head">
        <span className="turn-caret">{open ? "▾" : "▸"}</span>
        <span className="wc-icon">🌐</span>
        <span className="wc-host">{host || url.slice(0, 40)}</span>
      </div>
      {open && (
        <div className="wc-body">
          <div className="wc-url">{url}</div>
        </div>
      )}
    </div>
  );
}
