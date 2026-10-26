import { useSpica } from "./state";

/** 后台任务指示器 — 左上角 ⚙ N。 */
export default function BackgroundTasks() {
  const bgTasks = useSpica((s) => s.bgTasks);
  if (!bgTasks?.tasks?.length) return null;

  return (
    <span className="bg-tasks" title={bgTasks.tasks.map((t: any) => t.name).join(", ")}>
      ⚙ {bgTasks.tasks.length}
    </span>
  );
}
