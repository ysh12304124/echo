"""共享的 OpenAI 兼容 HTTP 客户端封装。

所有本地模型服务（LLM / VLM / Embedding / Whisper）都通过本地部署的
OpenAI 兼容接口访问。这里集中处理超时、重试与错误，便于后续替换服务。
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Optional

import httpx


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "not-needed",
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        response_format: Optional[dict] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "reasoning_effort": "none",
        }
        if response_format:
            payload["response_format"] = response_format
        if max_tokens:
            payload["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""

    async def embeddings(self, model: str, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json={"model": model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    async def transcribe(
        self, model: str, audio_path: str, language: Optional[str] = None
    ) -> dict:
        """调用 /audio/transcriptions，请求 verbose_json 以获取分段与时间戳。"""
        path = Path(audio_path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        form: dict[str, Any] = {
            "model": (None, model),
            "response_format": (None, "verbose_json"),
            "timestamp_granularities[]": (None, "segment"),
        }
        if language:
            form["language"] = (None, language)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            with path.open("rb") as f:
                files = {"file": (path.name, f, content_type), **form}
                resp = await client.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers=self._headers(),
                    files=files,
                )
            resp.raise_for_status()
            return resp.json()


def encode_image_data_url(image_path: str) -> str:
    path = Path(image_path)
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def parse_json_loose(text: str) -> Any:
    """从可能包含 markdown 代码块的模型输出中鲁棒解析 JSON。"""
    text = text.strip()
    if text.startswith("```"):
        # 去除 ```json ... ``` 包裹
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试截取第一个 { 或 [ 到最后一个 } 或 ]
        for open_ch, close_ch in (("[", "]"), ("{", "}")):
            start = text.find(open_ch)
            end = text.rfind(close_ch)
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    continue
        return None
