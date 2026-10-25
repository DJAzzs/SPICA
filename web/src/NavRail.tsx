import { useEffect, useRef, useState } from "react";
import { useSpica } from "./state";

/** 右侧对话节点导航轨：每个刻度 = 一条用户指令（语音/键盘），
 *  点击平滑跳转；悬停显示预览；滚动实时高亮当前区域。
 *  浅色 = 活页本穿孔（新拟物凹孔）；深色 = 毛玻璃刻度线。 */
export default function NavRail() {
  const msgs = useSpica((s) => s.msgs);
  const [active, setActive] = useState(-1);
  const rafRef = useRef(0);

  const nodes: { i: number; text: string }[] = [];
  msgs.forEach((m, i) => {
    if (m.role === "user") nodes.push({ i, text: m.text });
  });

  useEffect(() => {
    const el = document.querySelector(".chat-scroll");
    if (!el) return;
    const onScroll = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        const center = innerHeight / 2;
        let best = -1, bestD = Infinity;
        document.querySelectorAll<HTMLElement>("[id^='msg-']").forEach((n) => {
          const r = n.getBoundingClientRect();
          const d = Math.abs(r.top + r.height / 2 - center);
          if (d < bestD) { bestD = d; best = Number(n.dataset.i); }
        });
        setActive(best);
      });
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => { el.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(rafRef.current); };
  }, [msgs.length]);

  // 当前 active 消息落在哪个节点区间
  let activeNode = -1;
  nodes.forEach((n, k) => {
    const next = nodes[k + 1];
    if (active >= n.i && (next ? active < next.i : true)) activeNode = k;
  });

  const jump = (i: number) =>
    document.getElementById(`msg-${i}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });

  if (nodes.length < 2) return null;   // 节点太少不占空间

  return (
    <div className="nav-rail" aria-label="对话导航">
      {nodes.map((n, k) => (
        <button key={n.i} className={"rail-dot" + (k === activeNode ? " on" : "")}
          onClick={() => jump(n.i)} aria-label={`跳转到：${n.text.slice(0, 20)}`}>
          <span className="rail-tip">{n.text.slice(0, 30) || "…"}</span>
        </button>
      ))}
    </div>
  );
}
