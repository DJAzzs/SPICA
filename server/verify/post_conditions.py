"""L0: 程序化后置条件 — 零 LLM 成本，纯代码检查。"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path


def check_files_exist(created_files: list[str]) -> dict:
    """检查任务中创建的文件是否真的存在。"""
    missing = [f for f in created_files if not os.path.exists(f)]
    return {"pass": len(missing) == 0,
            "detail": f"缺失: {missing}" if missing else "全部存在"}


def check_syntax(modified_py_files: list[str]) -> dict:
    """检查修改过的 Python 文件语法是否合法。"""
    errors = []
    for f in modified_py_files:
        if not f.endswith(".py"):
            continue
        try:
            with open(f) as fh:
                ast.parse(fh.read())
        except SyntaxError as e:
            errors.append(f"{f}: {e}")
        except FileNotFoundError:
            pass  # 文件不存在由 L0 文件检查覆盖
    return {"pass": len(errors) == 0,
            "detail": "; ".join(errors[:3]) if errors else "语法全部合法"}


def check_json_valid(modified_json_files: list[str]) -> dict:
    """检查修改过的 JSON 文件是否可解析。"""
    errors = []
    for f in modified_json_files:
        if not f.endswith((".json", ".jsonl")):
            continue
        try:
            if f.endswith(".jsonl"):
                with open(f) as fh:
                    for line in fh:
                        if line.strip():
                            json.loads(line)
            else:
                with open(f) as fh:
                    json.load(fh)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            errors.append(f"{f}: {e}")
    return {"pass": len(errors) == 0,
            "detail": "; ".join(errors[:3]) if errors else "JSON 全部合法"}


def check_no_errors(tool_outputs: list[str]) -> dict:
    """检查工具输出中没有错误关键词。"""
    pattern = re.compile(
        r"Traceback|SyntaxError|ModuleNotFoundError|"
        r"Permission denied|CRITICAL|FATAL|exit code [1-9]",
        re.I)
    hits = []
    for out in tool_outputs:
        found = pattern.findall(out)
        if found:
            hits.extend(found[:3])
    return {"pass": len(hits) == 0,
            "detail": f"发现: {hits[:5]}" if hits else "无错误关键词"}


def check_tests(cwd: str, test_cmd: str | None) -> dict:
    """运行项目测试（如果有测试命令）。"""
    if not test_cmd:
        return {"pass": True, "detail": "无测试命令（跳过）"}
    try:
        r = subprocess.run(
            test_cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=120)
        passed = r.returncode == 0
        tail = (r.stdout or r.stderr or "").strip().split("\n")[-1][:100]
        return {"pass": passed, "detail": tail}
    except subprocess.TimeoutExpired:
        return {"pass": False, "detail": "测试超时（120s）"}
    except Exception as e:
        return {"pass": True, "detail": f"跳过: {e}"}


def run_l0(ctx: dict) -> list[dict]:
    """执行全部 L0 检查。

    ctx: {
        created_files: list[str],
        modified_files: list[str],
        tool_outputs: list[str],
        cwd: str,
        test_cmd: str | None,
    }
    """
    py_files = [f for f in ctx.get("modified_files", []) if f.endswith(".py")]
    json_files = [f for f in ctx.get("modified_files", []) if f.endswith((".json", ".jsonl"))]

    checks = [
        ("file_exists", check_files_exist(ctx.get("created_files", []))),
        ("syntax_valid", check_syntax(py_files)),
        ("json_valid", check_json_valid(json_files)),
        ("no_error_kw", check_no_errors(ctx.get("tool_outputs", []))),
        ("tests_pass", check_tests(ctx.get("cwd", ""), ctx.get("test_cmd"))),
    ]

    return [
        {"layer": 0, "type": name, **result}
        for name, result in checks
    ]
