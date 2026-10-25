import { useMemo } from "react";
import { marked } from "marked";

marked.setOptions({ breaks: true, gfm: true });

function sanitize(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, "")
    .replace(/ on\w+="[^"]*"/gi, "")
    .replace(/ on\w+='[^']*'/gi, "")
    .replace(/javascript:/gi, "");
}

/** Markdown 渲染 + 代码块点击复制（悬停浮现复制按钮）。 */
export default function Markdown({ text }: { text: string }) {
  const html = useMemo(() => {
    try {
      return sanitize(marked.parse(text || "", { async: false }) as string);
    } catch {
      return text;
    }
  }, [text]);

  const handleClick = (e: React.MouseEvent) => {
    const pre = (e.target as HTMLElement).closest("pre");
    if (!pre || pre.dataset.copied) return;
    const code = pre.querySelector("code");
    if (code) {
      navigator.clipboard.writeText(code.textContent || "").then(() => {
        pre.dataset.copied = "1";
        setTimeout(() => { delete pre.dataset.copied; }, 1500);
      }).catch(() => {});
    }
  };

  return (
    <div className="md" onClick={handleClick}
      dangerouslySetInnerHTML={{ __html: html }} />
  );
}
