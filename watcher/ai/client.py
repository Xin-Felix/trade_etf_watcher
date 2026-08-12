"""DeepSeek API 客户端（同步，用于 QThreadPool 线程中调用）."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from watcher.config import DeepSeekConfig

logger = logging.getLogger(__name__)

_SECRETS_ENV_PATH = Path(os.environ.get(
    "ETF_WATCHER_SECRETS",
    Path(os.path.expanduser("~/.config/etf_watcher/secrets.env")),
))


def _load_api_key() -> str | None:
    """从环境变量或 secrets.env 文件读取 DEEPSEEK_API_KEY."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key.strip()
    # 从 secrets.env 文件读取
    if _SECRETS_ENV_PATH.exists():
        try:
            for line in _SECRETS_ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "DEEPSEEK_API_KEY":
                    return v.strip().strip("\"'")
        except OSError:
            pass
    return None


def is_available() -> bool:
    """检查 DeepSeek API key 是否已配置."""
    return bool(_load_api_key())


class DeepSeekClient:
    """DeepSeek Chat API 同步客户端."""

    def __init__(self, cfg: DeepSeekConfig | None = None):
        if cfg is None:
            cfg = DeepSeekConfig()
        self.cfg = cfg
        self.api_key = _load_api_key() or ""
        self.base_url = cfg.base_url.rstrip("/")

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        enable_thinking: bool = True,
    ) -> dict[str, Any]:
        """发送聊天请求，返回解析后的 JSON 响应.

        如果 enable_thinking=True，使用 DeepSeek 深度思考模式，返回中包含 "thinking" 字段。
        如果模型返回的不是合法 JSON，尝试从 markdown 代码块中提取。
        失败时返回 {"error": "..."}.
        """
        if not self.api_key:
            return {"error": "未配置 DEEPSEEK_API_KEY，请在 API 设置中填写"}

        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": self.cfg.max_tokens,
        }

        if enable_thinking:
            # 深度思考模式：不能设 temperature/top_p，不能用 response_format
            payload["reasoning_effort"] = "high"
            # 注意：thinking 模式下不支持 response_format: json_object
            # 需要在 system prompt 中强调输出 JSON
        else:
            payload["temperature"] = temperature
            payload["response_format"] = {"type": "json_object"}

        try:
            with httpx.Client(timeout=self.cfg.timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            return {"error": "AI 请求超时（思考中），可增大超时或稍后重试"}
        except httpx.HTTPStatusError as e:
            logger.warning("DeepSeek API error: %s %s", e.response.status_code, e.response.text[:200])
            return {"error": f"AI 服务错误 ({e.response.status_code})"}
        except Exception as e:  # noqa: BLE001
            logger.warning("DeepSeek request failed: %s", e)
            return {"error": f"网络错误: {e}"}

        # 提取返回内容
        try:
            msg = data["choices"][0]["message"]
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or ""
        except (KeyError, IndexError):
            return {"error": "AI 响应格式异常"}

        # 尝试解析 JSON
        result = self._parse_json_response(content)
        # 附带思考过程
        if reasoning:
            result["_thinking"] = reasoning
        return result

    @staticmethod
    def _parse_json_response(content: str) -> dict[str, Any]:
        """解析 AI 返回的 JSON，支持 markdown 代码块包裹."""
        content = content.strip()
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # 尝试从 ```json ... ``` 中提取
        if "```" in content:
            start = content.find("```")
            end = content.rfind("```")
            if start != end:
                block = content[start:end]
                # 去掉第一行（```json）
                lines = block.split("\n", 1)
                if len(lines) > 1:
                    try:
                        return json.loads(lines[1])
                    except json.JSONDecodeError:
                        pass
        # 最后尝试找第一个 { 到最后一个 }
        brace_start = content.find("{")
        brace_end = content.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                return json.loads(content[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                pass
        return {"error": "AI 返回内容无法解析为 JSON", "raw": content[:500]}
