"""LLM 适配层：DeepSeek 官方 API + 自动降级。

OpenAI SDK 只在真正调用 DeepSeek 时导入，因此离线演示和单元测试
不需要安装 openai，也不会因为缺少 Key 启动失败。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from .config import Settings
from .schemas import LLMResponse, ToolCall


logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class DeepSeekLLM:
    is_mock = False
    mode = "deepseek"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_name = settings.model
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise LLMError("缺少 openai 依赖，请先执行：pip install openai") from exc
        if not settings.api_key:
            raise LLMError("未配置 DEEPSEEK_API_KEY")
        self._client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.request_timeout,
        )

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        models = [self.model_name]
        if self.settings.fallback_model and self.settings.fallback_model != self.model_name:
            models.append(self.settings.fallback_model)

        last_error: Optional[Exception] = None
        for model in models:
            for attempt in range(2):
                try:
                    return self._request(model, messages, tools, temperature, max_tokens)
                except Exception as exc:
                    last_error = exc
                    if self._is_model_error(exc) and model != models[-1]:
                        logger.warning("模型 %s 不可用，尝试回退模型 %s", model, models[-1])
                        break
                    if attempt == 0 and self._is_retryable(exc):
                        time.sleep(1.2)
                        continue
                    if self._is_model_error(exc) and model != models[-1]:
                        break
                    raise LLMError(self._friendly_error(exc)) from exc
        raise LLMError(self._friendly_error(last_error))

    def _request(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.settings.temperature if temperature is None else temperature,
            "max_tokens": self.settings.max_tokens if max_tokens is None else max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message
        tool_calls: List[ToolCall] = []
        for call in (message.tool_calls or []):
            raw_arguments = call.function.arguments or "{}"
            try:
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict):
                    arguments = {}
            except (TypeError, ValueError):
                arguments = {}
                logger.warning("工具参数不是合法 JSON：%s", raw_arguments[:200])
            tool_calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                )
            )

        usage = {}
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": int(getattr(response.usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(response.usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(response.usage, "total_tokens", 0) or 0),
            }
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            usage=usage,
            model=model,
            finish_reason=choice.finish_reason or "",
        )

    @staticmethod
    def _is_model_error(exc: Exception) -> bool:
        text = str(exc).lower()
        status = getattr(exc, "status_code", None)
        return status in {400, 404} and any(word in text for word in ["model", "not found", "does not exist", "invalid"])

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        return status in {429, 500, 502, 503, 504} or "timeout" in str(exc).lower()

    @staticmethod
    def _friendly_error(exc: Optional[Exception]) -> str:
        if exc is None:
            return "模型调用失败，请稍后重试。"
        text = str(exc)
        status = getattr(exc, "status_code", None)
        if status == 401:
            return "DeepSeek API Key 无效，请检查 DEEPSEEK_API_KEY。"
        if status == 402:
            return "DeepSeek 账户余额不足，请充值后重试。"
        if status == 429:
            return "模型请求过于频繁，请稍后再试。"
        if status in {500, 502, 503, 504}:
            return "模型服务暂时不可用，请稍后重试。"
        return "模型调用失败：%s" % text[:160]


class ResilientLLM:
    """主模型失败时自动降级到离线规则引擎，保证演示不中断。"""

    is_mock = False
    mode = "deepseek"

    def __init__(self, primary: DeepSeekLLM, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback
        self.model_name = primary.model_name
        self.last_error: Optional[str] = None
        self.used_fallback = False

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        try:
            response = self.primary.chat(messages, tools, temperature, max_tokens)
            self.used_fallback = False
            return response
        except LLMError as exc:
            self.last_error = str(exc)
            self.used_fallback = True
            logger.warning("DeepSeek 调用失败，降级到离线引擎：%s", exc)
            return self.fallback.chat(messages, tools, temperature, max_tokens)


def build_llm(settings: Settings) -> Any:
    from .mock_llm import MockLLM

    mock = MockLLM(settings)
    if settings.offline:
        return mock
    try:
        primary = DeepSeekLLM(settings)
    except LLMError as exc:
        logger.warning("无法初始化 DeepSeek，使用离线模式：%s", exc)
        return mock
    return ResilientLLM(primary, mock)
