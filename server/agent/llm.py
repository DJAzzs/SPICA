"""LLM 客户端：与 DSH 同一 provider（zai-coding-cn，OpenAI 兼容）。

密钥解析顺序：settings.llm_api_key → 环境变量 ZAI_CODING_CN_API_KEY →
~/.dsh/.credentials.yaml refs（与 DSH web profile 完全同源）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx

from server.config import load_settings

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
CRED_FILE = Path.home() / ".dsh" / ".credentials.yaml"


def _key_from_dsh_credentials() -> str:
    try:
        m = re.search(r"ZAI_CODING_CN_API_KEY:\s*(\S+)", CRED_FILE.read_text())
        return m.group(1) if m else ""
    except Exception:
        return ""


class LLMClient:
    def __init__(self, settings: dict | None = None):
        import os
        self.settings = settings or load_settings()
        self.api_key: str = (
            (self.settings.get("llm_api_key") or "")
            or os.environ.get("ZAI_CODING_CN_API_KEY", "")
            or _key_from_dsh_credentials()
        )
        self.base_url: str = (
            self.settings.get("llm_base_url") or DEFAULT_BASE_URL
        ).rstrip("/")

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
        timeout: float = 60.0,
        thinking: str | None = None,
    ) -> str | AsyncIterator[str]:
        """OpenAI 兼容 /chat/completions。stream=True 返回增量迭代器。
        thinking="disabled" 关闭推理（glm 系推理模型的轻量快速模式）。"""
        model = model or self.settings.get("llm_model_rewrite", "glm-5.3")
        body: dict = {"model": model, "messages": messages, "stream": stream}
        if max_tokens:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if thinking:
            body["thinking"] = {"type": thinking}
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async def _stream() -> AsyncIterator[str]:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions",
                    json=body, headers=headers,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            delta = json.loads(data)["choices"][0]["delta"]
                        except Exception:
                            continue
                        piece = delta.get("content") or delta.get("reasoning_content") or ""
                        if piece:
                            yield piece

        if stream:
            return _stream()
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""
