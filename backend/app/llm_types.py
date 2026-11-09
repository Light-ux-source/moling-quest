"""LLM 基础类型、JSON 容错解析与错误映射（与具体 SDK 解耦）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import Settings


class LLMError(RuntimeError):
    """业务层可读的模型错误。"""


@dataclass
class LLMResult:
    data: Dict[str, Any]
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cny: float = 0.0
    model: str = ""


def extract_json(text: str) -> Dict[str, Any]:
    """从模型输出中稳健地取出 JSON 对象（容忍 ```json 包裹、前后寒暄）。"""
    if not text:
        raise LLMError("模型返回空内容")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    raise LLMError(f"无法解析模型输出为 JSON: {text[:200]}")


def estimate_cost(tokens_in: int, tokens_out: int, settings: Settings) -> float:
    return round(
        tokens_in / 1_000_000 * settings.cost_input_per_m
        + tokens_out / 1_000_000 * settings.cost_output_per_m,
        6,
    )


def map_llm_error(exc: Exception) -> LLMError:
    """把 OpenAI/LangChain/网络异常翻译成用户可读的中文错误。"""
    if isinstance(exc, LLMError):
        return exc

    message = str(exc)
    lowered = message.lower()
    status: Optional[int] = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)

    if status == 401:
        return LLMError("DeepSeek API Key 无效，请检查后端 .env 配置")
    if status == 402:
        return LLMError("DeepSeek 账户余额不足，请充值后重试")
    if status == 403:
        return LLMError("DeepSeek 拒绝了本次请求，请检查 Key 权限")
    if status == 429:
        return LLMError("请求过于频繁，请稍后再试")
    if status and 500 <= int(status) < 600:
        return LLMError("DeepSeek 服务暂时不可用，请稍后重试")
    if status == 400:
        return LLMError(f"AI 请求参数有误：{message[:120]}")

    if any(word in lowered for word in ("timeout", "timed out", "read timed")):
        return LLMError("AI 生成超时，请稍后重试")
    if any(word in lowered for word in ("connection", "network", "ssl", "dns", "proxy")):
        return LLMError("网络连接失败，请检查后端网络或代理设置")

    return LLMError(f"AI 调用失败：{message[:120]}")