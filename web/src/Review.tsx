import { useEffect } from "react";
import { useSpica, send } from "./state";

/** 审阅模式：最近一条任务的转写+改写对照（非演示态可开）。 */
export default function Review() {
  const review = useSpica((s) => s.review);
  const rewriteFinal = useSpica((s) => s.rewriteFinal);
  const partial = useSpica((s) => s.partial);
  useEffect(() => { send({ t: "review_get" }); }, []);
  const items = review.length ? review : [];
  return (
    <div className="panel">
      <div className="inner" style={{ width: 720 }}>
        <h1>审阅</h1>
        {partial && <div className="review-item"><div className="role">实时转写</div>{partial}</div>}
        {rewriteFinal && <div className="review-item"><div className="role">改写终稿</div>{rewriteFinal}</div>}
        {items.map((e: any, i: number) => (
          <div className="review-item" key={i}>
            <div className="role">{e.role}</div>
            {e.text}
          </div>
        ))}
        {!items.length && !rewriteFinal && <div className="hint">暂无内容——说一句话唤醒后这里会出现转写与改写对照。</div>}
        <div className="btn-row"><a className="btn" href="#/">返回</a></div>
      </div>
    </div>
  );
}
