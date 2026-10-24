import { useMemo } from "react";
import { marked } from "marked";

marked.setOptions({ breaks: true, gfm: true });

/** 基础净化：本地 Agent 输出，剥离脚本类标签与内联事件（纵深防御）。 */
function sanitize(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, "")
    .replace(/ on\w+="[^"]*"/gi, "")
    .replace(/ on\w+='[^']*'/gi, "")
    .replace(/javascript:/gi, "");
}

/** 受限 Markdown 渲染（代码块/行内代码/粗斜体/标题/列表/链接/引用/表格）。 */
export default function Markdown({ text }: { text: string }) {
  const html = useMemo(() => {
    try {
      return sanitize(marked.parse(text || "", { async: false }) as string);
    } catch {
      return text;
    }
  }, [text]);
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}
