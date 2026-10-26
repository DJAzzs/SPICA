"""SPICA 多智能体执行器 — 并行 DSH 会话 + 交叉验证 + 结果合成。

预设方案 + 自定义 Agent 配置。每个 Agent 独立 DSH 会话（上下文隔离），
结果交叉比对后合成综合报告。

架构（借鉴 PHLOX 的角色分工 + 对抗审查理念）：
  任务 → 分发给 N 个 Agent 并行执行
       → 结果收集
       → 审查者 Agent 交叉验证
       → 合成者 Agent 综合报告
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """单个 Agent 的配置。"""
    name: str          # 显示名
    model: str         # 使用的模型
    role: str          # 角色 prompt（"你是一个搜索者…"）
    temperature: float = 0.5


# ============================================================
# 预设方案
# ============================================================

PRESETS: dict[str, dict] = {
    "investigation": {
        "label": "🔍 调查",
        "desc": "搜索 + 汇总 + 审查",
        "agents": [
            AgentConfig(
                name="搜索者", model="glm-5.3-flash",
                role="你是一个信息搜索专家。负责从多个角度收集与任务相关的原始信息，"
                     "提供事实和数据，不做主观判断。"),
            AgentConfig(
                name="汇总者", model="glm-5.3",
                role="你是一个信息综合专家。负责整合多个来源的信息，"
                     "提炼关键发现，去除冗余和矛盾。"),
            AgentConfig(
                name="审查者", model="glm-5.3",
                role="你是一个事实核查专家。负责校验信息的准确性和完整性，"
                     "标记可疑或不一致的内容。"),
        ],
    },
    "code_review": {
        "label": "🧪 代码评审",
        "desc": "编码 + 测试 + 审查",
        "agents": [
            AgentConfig(
                name="编码者", model="glm-5.3",
                role="你是一个资深开发者。负责分析和编写代码解决方案，"
                     "注重代码质量和可维护性。"),
            AgentConfig(
                name="测试者", model="glm-5.3-flash",
                role="你是一个测试工程师。负责为代码设计测试用例，"
                     "找出边界情况和潜在 bug。"),
            AgentConfig(
                name="审查者", model="glm-5.3",
                role="你是一个代码审查专家。负责从架构、安全、性能角度审查代码，"
                     "提出改进建议。"),
        ],
    },
    "analysis": {
        "label": "📊 分析",
        "desc": "数据 + 分析 + 报告",
        "agents": [
            AgentConfig(
                name="数据者", model="glm-5.3-flash",
                role="你是一个数据收集专家。负责整理任务相关的数据、事实和背景信息。"),
            AgentConfig(
                name="分析者", model="glm-5.3",
                role="你是一个深度分析专家。负责从数据中提取洞察，"
                     "进行因果分析和趋势判断。"),
            AgentConfig(
                name="报告者", model="glm-5.3",
                role="你是一个报告撰写专家。负责将分析结果整理成结构清晰、"
                     "易于理解的报告。"),
        ],
    },
    "adversarial": {
        "label": "⚔️ 对抗",
        "desc": "正方 + 反方 + 裁判",
        "agents": [
            AgentConfig(
                name="正方", model="glm-5.3",
                role="你是支持方。全力论证任务的正面价值和可行性，"
                     "提供最强支持论据。"),
            AgentConfig(
                name="反方", model="glm-5.3",
                role="你是反对方。全力论证任务的风险和不可行性，"
                     "提供最强反对论据。注意要基于事实，不是为反对而反对。"),
            AgentConfig(
                name="裁判", model="glm-5.3",
                role="你是中立裁判。综合正反双方论据，做出平衡的判断和建议。"),
        ],
    },
}


# ============================================================
# 多智能体执行器
# ============================================================

class MultiAgentExecutor:
    """并行执行多 Agent 任务并合成结果。"""

    def __init__(self, llm, broadcast):
        """llm: SPICA 的 LLM 客户端（用于合成报告）
        broadcast: 异步广播函数
        """
        self.llm = llm
        self.broadcast = broadcast

    async def run(self, task: str, agents: list[AgentConfig],
                  preset_key: str = "") -> dict:
        """执行多智能体任务。

        流程：
        1. 并行：每个 Agent 独立接收任务（带角色 prompt）并生成回答
        2. 交叉：最后一个 Agent（通常是审查者/裁判）看到前面所有结果
        3. 合成：LLM 综合所有 Agent 的输出，生成最终报告
        """
        t0 = time.time()
        results: list[dict] = []

        # 阶段一：并行执行（最后一个 Agent 串行，因为需要看前面结果）
        parallel_agents = agents[:-1] if len(agents) > 1 else agents
        final_agent = agents[-1] if len(agents) > 1 else None

        await self.broadcast({"t": "ma_progress",
            "phase": "parallel", "total": len(parallel_agents), "done": 0,
            "preset": preset_key})

        async def run_agent(agent: AgentConfig, idx: int) -> dict:
            """单个 Agent 执行任务。"""
            try:
                prompt = f"（你的角色：{agent.role}）\n\n任务：{task}"
                response = await self.llm.chat(
                    [{"role": "user", "content": prompt}],
                    model=agent.model,
                    max_tokens=800,
                    temperature=agent.temperature,
                    thinking="disabled",
                    timeout=30.0)

                result = {
                    "agent": agent.name,
                    "model": agent.model,
                    "output": (response or "").strip()[:1000],
                    "status": "done",
                }
            except Exception as e:
                result = {
                    "agent": agent.name,
                    "model": agent.model,
                    "output": f"执行失败: {e}",
                    "status": "error",
                }

            results.append(result)
            await self.broadcast({"t": "ma_progress",
                "phase": "parallel",
                "total": len(parallel_agents),
                "done": len(results),
                "agent": agent.name,
                "status": result["status"]})
            return result

        # 并行执行前 N-1 个 Agent
        tasks = [run_agent(a, i) for i, a in enumerate(parallel_agents)]
        await asyncio.gather(*tasks)

        # 阶段二：最终 Agent（审查者/裁判）看所有结果
        if final_agent:
            await self.broadcast({"t": "ma_progress",
                "phase": "synthesis", "agent": final_agent.name})
            context = "\n\n---\n\n".join(
                f"【{r['agent']}】\n{r['output']}"
                for r in results if r["status"] == "done")

            try:
                synth_prompt = (
                    f"（你的角色：{final_agent.role}）\n\n"
                    f"原始任务：{task}\n\n"
                    f"以下是其他 Agent 的回答：\n\n{context}\n\n"
                    f"请综合以上信息，给出你的最终判断。")
                synth_response = await self.llm.chat(
                    [{"role": "user", "content": synth_prompt}],
                    model=final_agent.model,
                    max_tokens=800,
                    temperature=0.3,
                    thinking="disabled",
                    timeout=30.0)
                results.append({
                    "agent": final_agent.name,
                    "model": final_agent.model,
                    "output": (synth_response or "").strip()[:1000],
                    "status": "done",
                })
            except Exception as e:
                results.append({
                    "agent": final_agent.name,
                    "model": final_agent.model,
                    "output": f"合成失败: {e}",
                    "status": "error",
                })

        # 阶段三：生成综合报告
        elapsed = time.time() - t0
        report = self._generate_report(task, results, elapsed)

        await self.broadcast({"t": "ma_progress",
            "phase": "done", "elapsed": round(elapsed, 1)})

        return report

    def _generate_report(self, task: str, results: list[dict],
                         elapsed: float) -> dict:
        """汇总所有 Agent 结果 → 综合报告事件。"""
        successful = [r for r in results if r["status"] == "done"]
        return {
            "t": "ma_result",
            "task": task[:100],
            "agents": [
                {"name": r["agent"], "model": r["model"],
                 "status": r["status"],
                 "output": r["output"]}
                for r in results
            ],
            "summary": successful[-1]["output"] if successful else "全部失败",
            "total_agents": len(results),
            "successful": len(successful),
            "elapsed_s": round(elapsed, 1),
        }


async def run_multi_agent(sem, task: str,
                          preset_key: str = "investigation") -> None:
    """SPICA 入口：多智能体任务执行。"""
    preset = PRESETS.get(preset_key, PRESETS["investigation"])
    executor = MultiAgentExecutor(sem.llm, sem.broadcast)

    await sem.broadcast({"t": "msg", "role": "system",
        "text": f"👥 多智能体模式：{preset['label']}（{len(preset['agents'])} 个 Agent）"})

    report = await executor.run(task, preset["agents"], preset_key)

    # 广播结果到对话流
    for r in report["agents"]:
        await sem.broadcast({"t": "msg", "role": "assistant",
            "text": f"**{r['name']}**（{r['model']}）\n\n{r['output']}"})

    await sem.broadcast({"t": "msg", "role": "system",
        "text": f"👥 多智能体完成：{report['successful']}/{report['total_agents']} "
                f"成功，耗时 {report['elapsed_s']}s"})
