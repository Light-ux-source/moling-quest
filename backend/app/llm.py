"""LLM 适配层。

- 真实模式：DeepSeek OpenAI 兼容接口（默认 deepseek-flash），强制 JSON 输出；
- Mock 模式：无 Key 时也能跑通完整链路，按 task + context 生成确定性数据；
- 对上层暴露统一 `chat_json(task, system, user, context)`，业务代码不关心底层实现。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


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


class BaseLLM:
    name = "base"
    model = ""

    async def chat_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        context: Optional[Dict[str, Any]] = None,
        temperature: float = 0.3,
        max_tokens: int = 3000,
    ) -> LLMResult:  # pragma: no cover - 接口定义
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class DeepSeekLLM(BaseLLM):
    name = "deepseek"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.deepseek_model
        self._client = httpx.AsyncClient(
            base_url=settings.deepseek_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.deepseek_timeout, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        context: Optional[Dict[str, Any]] = None,
        temperature: float = 0.3,
        max_tokens: int = 3000,
    ) -> LLMResult:
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        # DeepSeek 思考模式默认开启，必须显式 disabled 才能关闭（官方文档 2026-11 核实）
        if self.settings.deepseek_thinking:
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = "high"
        else:
            body["thinking"] = {"type": "disabled"}

        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key.strip()}",
            "Content-Type": "application/json",
        }

        last_error: Optional[Exception] = None
        for attempt in range(self.settings.deepseek_max_retries + 1):
            try:
                resp = await self._client.post("/chat/completions", json=body, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("LLM 网络错误 task=%s attempt=%s err=%s", task, attempt, exc)
                await asyncio.sleep(1.2 * (attempt + 1))
                continue

            if resp.status_code == 402:
                raise LLMError("DeepSeek 账户余额不足，请充值后重试")
            if resp.status_code == 401:
                raise LLMError("DeepSeek API Key 无效，请检查后端 .env 配置")
            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = LLMError(f"DeepSeek 返回 {resp.status_code}: {resp.text[:200]}")
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 400 and "response_format" in body:
                # 极少数情况下模型/SDK 不接受 JSON mode，降级重试
                logger.warning("JSON mode 被拒绝，降级为纯文本+提示重试")
                body.pop("response_format", None)
                last_error = LLMError(resp.text[:300])
                continue
            if resp.status_code == 400 and "thinking" in body and "thinking" in resp.text.lower():
                # 兼容旧模型/网关不识别 thinking 参数
                logger.warning("thinking 参数不被接受，去掉后重试")
                body.pop("thinking", None)
                body.pop("reasoning_effort", None)
                last_error = LLMError(resp.text[:300])
                continue
            if resp.status_code >= 400:
                raise LLMError(f"DeepSeek 调用失败 {resp.status_code}: {resp.text[:300]}")

            payload = resp.json()
            usage = payload.get("usage") or {}
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
            content = (payload.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            data = extract_json(content)
            return LLMResult(
                data=data,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_cny=estimate_cost(tokens_in, tokens_out, self.settings),
                model=payload.get("model", self.model),
            )

        raise LLMError(f"DeepSeek 调用重试耗尽: {last_error}")


class MockLLM(BaseLLM):
    """离线模式：保证「输入 → 出题 → 答题 → 报告」端到端可演示、可测试。"""

    name = "mock"
    model = "mock-deepseek-flash"

    async def chat_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        context: Optional[Dict[str, Any]] = None,
        temperature: float = 0.3,
        max_tokens: int = 3000,
    ) -> LLMResult:
        ctx = context or {}
        await asyncio.sleep(0.25)
        if task == "digest":
            data = self._digest(ctx)
        elif task == "generate":
            data = self._generate(ctx)
        elif task == "grade":
            data = self._grade(ctx)
        elif task == "report":
            data = self._report(ctx)
        else:
            data = {"ok": True}
        return LLMResult(data=data, model=self.model)

    # ---------------- builders ----------------
    @staticmethod
    def _topic(ctx: Dict[str, Any]) -> str:
        return str(ctx.get("topic") or "这个主题")

    def _digest(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        topic = self._topic(ctx)
        return {
            "title": f"{topic} 核心知识梳理",
            "summary": f"围绕「{topic}」，本次学习聚焦概念定义、关键机制与常见误区三个层面。",
            "key_points": [
                {"point": f"{topic} 的基本定义与适用边界", "evidence": "来源于主题综述与官方文档。", "source_url": ""},
                {"point": f"{topic} 的核心机制与关键步骤", "evidence": "来源于原理讲解类资料。", "source_url": ""},
                {"point": f"{topic} 的典型应用场景与反例", "evidence": "来源于实践案例。", "source_url": ""},
            ],
            "misconceptions": [f"把 {topic} 的某个特例当成通用结论", f"混淆 {topic} 与相邻概念的前提条件"],
            "prerequisites": ["基础术语", "常见场景"],
            "mock": True,
        }

    def _generate(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        topic = self._topic(ctx)
        count = int(ctx.get("count") or 5)
        types: List[str] = ctx.get("types") or ["single_choice", "multiple_choice", "true_false", "short_answer"]
        rng = random.Random(hash(topic) & 0xFFFF)
        questions: List[Dict[str, Any]] = []
        for i in range(count):
            qtype = types[i % len(types)]
            seq = i + 1
            if qtype in ("single_choice", "true_false"):
                options = (
                    [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
                    if qtype == "true_false"
                    else [
                        {"key": "A", "text": f"{topic} 的核心定义"},
                        {"key": "B", "text": f"与 {topic} 无关的干扰项"},
                        {"key": "C", "text": f"{topic} 的常见误用"},
                        {"key": "D", "text": "以上都不对"},
                    ]
                )
                correct = "A" if qtype == "true_false" else rng.choice(["A", "C"])
                questions.append(
                    {
                        "type": qtype,
                        "stem": f"关于「{topic}」，下列说法正确的是？（第 {seq} 题 · 模拟）",
                        "options": options,
                        "correct_answer": correct,
                        "explanation": f"本题考查 {topic} 的基本概念。正确选项体现了核心定义，其余选项混淆了边界条件。",
                        "difficulty": "easy" if seq <= 2 else "medium",
                        "rubric": [],
                        "source_refs": [],
                    }
                )
            elif qtype == "multiple_choice":
                questions.append(
                    {
                        "type": "multiple_choice",
                        "stem": f"以下哪些属于「{topic}」的关键要素？（多选 · 模拟）",
                        "options": [
                            {"key": "A", "text": "核心概念"},
                            {"key": "B", "text": "适用条件"},
                            {"key": "C", "text": "无关的营销话术"},
                            {"key": "D", "text": "典型反例"},
                        ],
                        "correct_answer": ["A", "B", "D"],
                        "explanation": f"关键要素需要同时满足概念、条件与反例三个维度；营销话术不属于知识本身。",
                        "difficulty": "medium",
                        "rubric": [],
                        "source_refs": [],
                    }
                )
            else:
                questions.append(
                    {
                        "type": "short_answer",
                        "stem": f"请用 2～3 句话说明「{topic}」的核心机制，并举一个适用场景。（模拟）",
                        "options": [],
                        "correct_answer": [
                            f"说明 {topic} 的定义与作用",
                            "描述关键步骤或因果关系",
                            "给出一个具体适用场景",
                        ],
                        "explanation": f"简答题按要点给分：定义、机制、场景各占一部分。",
                        "difficulty": "hard",
                        "rubric": [
                            f"提到 {topic} 的定义或目标",
                            "描述了机制/流程",
                            "给出具体场景",
                        ],
                        "source_refs": [],
                    }
                )
        return {"questions": questions}

    def _grade(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        answer = str(ctx.get("user_answer") or "").strip()
        rubric: List[str] = ctx.get("rubric") or []
        hits = 0
        for point in rubric:
            keyword = point.replace("提到", "").strip()[:6]
            if keyword and keyword in answer:
                hits += 1
        if not rubric:
            hits = 1 if len(answer) >= 20 else 0
        score = min(1.0, hits / max(1, len(rubric))) if rubric else (1.0 if hits else 0.0)
        if len(answer) >= 12 and score < 0.4:
            score = 0.4
        return {
            "score": round(score, 2),
            "correct": score >= 0.6,
            "feedback": (
                "要点覆盖较完整，表述清晰。" if score >= 0.8
                else "覆盖了部分要点，建议补充机制与场景细节。" if score >= 0.4
                else "答案与要点关联较弱，建议先回看解析中的关键概念。"
            ),
            "missing_points": [] if score >= 0.8 else rubric[: max(0, len(rubric) - hits)],
        }

    def _report(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        topic = self._topic(ctx)
        accuracy = float(ctx.get("accuracy") or 0)
        wrong_seqs = ctx.get("wrong_seqs") or []
        gaps = (
            [f"第 {w.get('seq')} 题（{w.get('type_label')}）涉及的知识点仍需巩固" for w in wrong_seqs[:3]]
            or [f"{topic} 的整体框架已基本掌握"]
        )
        return {
            "summary": (
                f"本次「{topic}」练习正确率 {int(accuracy * 100)}%，"
                + ("整体掌握良好，可以进入更难的题目。" if accuracy >= 0.8 else "基础概念已建立，但细节与应用还需加强。")
            ),
            "level_tag": "掌握良好" if accuracy >= 0.8 else "需要巩固" if accuracy >= 0.5 else "建议重学",
            "knowledge_gaps": gaps,
            "next_steps": [
                "回看错题的解析，用自己的话复述一遍关键概念",
                "针对薄弱点再练一组同主题题目",
                "尝试把概念应用到一个真实场景中",
            ],
            "suggested_topics": [f"{topic} 进阶", f"{topic} 的常见误区", f"{topic} 实战案例"],
        }


_llm: Optional[BaseLLM] = None


def get_llm() -> BaseLLM:
    global _llm
    if _llm is None:
        settings = get_settings()
        _llm = MockLLM() if settings.is_mock else DeepSeekLLM(settings)
        logger.info("LLM 初始化: %s (%s)", _llm.name, _llm.model)
    return _llm


async def close_llm() -> None:
    global _llm
    if _llm is not None:
        await _llm.aclose()
        _llm = None