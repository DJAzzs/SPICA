"""SPICA 模式系统：四种工作流引擎。

每种模式改变整条管线（上下文注入/执行流程/工具策略/输出格式），
不是提示词模板。与模型选择完全正交。

模式：
  minimal  极简 (PTC)：跳过分类/改写，最小上下文，静默执行，Token 省 60%+
  standard 常规：现有默认行为
  coding   编程：三阶段流水线（项目分析→实现+强制测试→交付报告）
  custom   定制：工作区切换为 SPICA 源码，代码地图+安全约束
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import time
from pathlib import Path

# ============================================================
# 模式定义
# ============================================================

MODES = {
    "minimal": {
        "label": "极简",
        "icon": "⚡",
        "desc": "最短路径，Token 省 60%+",
    },
    "standard": {
        "label": "常规",
        "icon": "○",
        "desc": "默认行为",
    },
    "coding": {
        "label": "编程",
        "icon": "⌨",
        "desc": "三阶段流水线，强制测试",
    },
    "custom": {
        "label": "定制",
        "icon": "🔧",
        "desc": "修改 SPICA 自身",
    },
}


# ============================================================
# 极简模式 (PTC) — 管线瘦身
# ============================================================

class MinimalPipeline:
    """极简模式：砍掉一切可省的步骤。"""

    # 高频意图正则（跳过 LLM 分类）
    FAST_INTENTS = [
        (re.compile(r"暂停|等一下|先停|停一|hold on", re.I), "pause"),
        (re.compile(r"继续|恢复", re.I), "resume"),
        (re.compile(r"放一首|播一首|播放|来首|来一首|放歌|听首|music|song", re.I), "music_play"),
        (re.compile(r"停.*音乐|关.*音乐|别放|music.*stop", re.I), "music_stop"),
        (re.compile(r"导出|export", re.I), "export"),
    ]

    @classmethod
    def fast_classify(cls, text: str) -> str | None:
        """正则快判，替代 LLM 意图分类（0ms）。"""
        for pattern, intent in cls.FAST_INTENTS:
            if pattern.search(text):
                return intent
        return None

    @classmethod
    def should_skip_rewrite(cls) -> bool:
        return True

    @classmethod
    def context_inject(cls, sem) -> str:
        """极简：不注入任何前缀（省 500+ tokens）。"""
        return ""

    @classmethod
    def tool_output_limit(cls) -> int:
        """工具输出截断长度。"""
        return 200

    @classmethod
    def should_narrate_steps(cls) -> bool:
        """过程不播报，只播最终结果。"""
        return False

    @classmethod
    def should_evolve(cls) -> bool:
        """暂停自进化。"""
        return False

    @classmethod
    def auto_compact_rounds(cls) -> int:
        """超过 N 轮自动压缩。"""
        return 10


# ============================================================
# 编程模式 — 三阶段流水线
# ============================================================

class CodingPipeline:
    """编程模式：项目分析→实现+强制测试→交付报告。"""

    @staticmethod
    def analyze_project(cwd: str) -> dict:
        """阶段一：扫描项目结构，生成项目地图。"""
        root = Path(cwd)
        info = {
            "languages": [],
            "framework": None,
            "has_tests": False,
            "has_build": False,
            "build_cmd": None,
            "test_cmd": None,
            "file_count": 0,
            "key_files": [],
        }

        if not root.exists():
            return info

        # 扫描文件
        for p in root.rglob("*"):
            if p.is_file() and not any(x in str(p) for x in
                    [".git", "node_modules", "__pycache__", ".venv", "dist"]):
                info["file_count"] += 1
                if info["file_count"] > 500:
                    break

        # 语言检测
        exts = set()
        for p in root.glob("*"):
            if p.is_file():
                exts.add(p.suffix)
        if ".py" in exts or (root / "requirements.txt").exists():
            info["languages"].append("Python")
        if ".ts" in exts or ".tsx" in exts or (root / "package.json").exists():
            info["languages"].append("TypeScript")
        if ".rs" in exts or (root / "Cargo.toml").exists():
            info["languages"].append("Rust")
        if ".go" in exts or (root / "go.mod").exists():
            info["languages"].append("Go")

        # 构建系统检测
        if (root / "package.json").exists():
            info["framework"] = "Node.js"
            info["has_build"] = True
            pkg = {}
            try:
                pkg = json.loads((root / "package.json").read_text())
                if "test" in pkg.get("scripts", {}):
                    info["has_tests"] = True
                    info["test_cmd"] = "npm test"
            except Exception:
                pass
        if (root / "Makefile").exists():
            info["has_build"] = True
            if not info["test_cmd"]:
                info["test_cmd"] = "make test"
        if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
            info["has_tests"] = True
            if not info["test_cmd"]:
                info["test_cmd"] = "pytest --tb=no -q"

        # 关键文件
        for name in ["README.md", "package.json", "requirements.txt",
                      "Makefile", "pyproject.toml", "Cargo.toml", ".env"]:
            if (root / name).exists():
                info["key_files"].append(name)

        return info

    @staticmethod
    def project_map_prompt(info: dict) -> str:
        """生成项目地图注入 System Prompt。"""
        parts = []
        if info["languages"]:
            parts.append(f"项目语言: {', '.join(info['languages'])}")
        if info["framework"]:
            parts.append(f"框架: {info['framework']}")
        if info["file_count"]:
            parts.append(f"文件数: ~{info['file_count']}")
        if info["test_cmd"]:
            parts.append(f"测试命令: {info['test_cmd']}")
        if info["key_files"]:
            parts.append(f"关键文件: {', '.join(info['key_files'][:10])}")
        if parts:
            return "〔项目地图〕" + "；".join(parts) + "\n"
        return ""

    @staticmethod
    def check_syntax(file_path: str) -> tuple[bool, str]:
        """检查 Python 文件语法。"""
        if not file_path.endswith(".py"):
            return True, ""
        try:
            with open(file_path) as f:
                ast.parse(f.read())
            return True, ""
        except SyntaxError as e:
            return False, str(e)

    @staticmethod
    def run_tests(cwd: str, test_cmd: str | None) -> tuple[bool, str]:
        """运行项目测试。"""
        if not test_cmd:
            return True, "无测试"
        try:
            r = subprocess.run(
                test_cmd, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=120)
            passed = r.returncode == 0
            output = (r.stdout + r.stderr)[-500:]
            return passed, output
        except Exception as e:
            return False, str(e)

    @staticmethod
    def delivery_report(files_changed: list, test_result: tuple) -> str:
        """阶段三：结构化交付报告。"""
        parts = []
        if files_changed:
            parts.append(f"变更文件: {len(files_changed)} 个")
        if test_result:
            status = "✓ 通过" if test_result[0] else "✗ 失败"
            parts.append(f"测试: {status}")
        return "\n".join(parts)


# ============================================================
# 定制模式 — SPICA 源码工作区
# ============================================================

class CustomPipeline:
    """定制模式：工作区切换为 SPICA 自身源码。"""

    # SPICA 项目根（由调用者注入）
    SPICA_ROOT: Path = None

    # 只读目录（不可修改）
    READONLY = [".git", "run", "node_modules", "__pycache__", ".venv", "models"]

    # 核心文件（修改需确认）
    CRITICAL = [
        "server/main.py",
        "server/agent/semantics.py",
        "server/ws/server.py",
    ]

    # 代码地图
    CODE_MAP = (
        "〔SPICA 代码地图〕\n"
        "server/ — Python 后端\n"
        "  main.py          入口\n"
        "  config.py        配置与默认值\n"
        "  agent/           DSH桥/改写/路由/语义/模式\n"
        "  voice/           唤醒/VAD/ASR/声纹/管线\n"
        "  tts/             TTS引擎/播报/应答包\n"
        "  ws/              WebSocket协议/REST\n"
        "  sessions.py      会话存储\n"
        "  evolution/       自进化（记忆/技能）\n"
        "  media/           MusicFree/偏好\n"
        "web/src/ — React 前端\n"
        "  App.tsx          主界面\n"
        "  state.ts         状态管理\n"
        "  Sidebar.tsx      侧边栏\n"
        "  ModelPicker.tsx  模型选择\n"
        "  styles.css       全部样式\n"
        "tests/ — 104+ 单测\n"
        "docs/ — 设计规范\n"
    )

    @classmethod
    def is_readonly(cls, path: str) -> bool:
        """检查路径是否在只读区域。"""
        rel = Path(path)
        try:
            rel = rel.relative_to(cls.SPICA_ROOT)
        except ValueError:
            return False
        parts = rel.parts
        for ro in cls.READONLY:
            if ro in parts:
                return True
        return False

    @classmethod
    def is_critical(cls, path: str) -> bool:
        """检查是否为核心文件（修改需确认）。"""
        rel = str(Path(path).relative_to(cls.SPICA_ROOT))
        return rel in cls.CRITICAL

    @classmethod
    def verify_build(cls) -> tuple[bool, str]:
        """修改后自动构建验证。"""
        # 前端构建
        try:
            r = subprocess.run(
                "npm run build", shell=True, cwd=str(cls.SPICA_ROOT / "web"),
                capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                return False, f"前端构建失败: {r.stderr[-300:]}"
        except Exception as e:
            return False, f"构建异常: {e}"

        # 后端测试
        try:
            venv_py = cls.SPICA_ROOT / ".venv" / "bin" / "python"
            r = subprocess.run(
                [str(venv_py), "-m", "pytest", "tests/", "-q", "--tb=no"],
                cwd=str(cls.SPICA_ROOT),
                capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                return False, f"测试失败: {r.stdout[-300:]}"
        except Exception as e:
            return False, f"测试异常: {e}"

        return True, "构建+测试通过"
