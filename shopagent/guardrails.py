"""输入/输出护栏：限流、PII 脱敏、参数清洗、回复裁剪与事实一致性检查。"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple


PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
ID_CARD_RE = re.compile(r"(?<!\d)(\d{6})(\d{8})(\d{3}[\dXx])(?!\d)")
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
TRACKING_RE = re.compile(r"(?<![A-Za-z0-9])(?:SF|ZT|YT|JD|EMS|DBL)\d{6,}(?![A-Za-z0-9])", re.IGNORECASE)
ORDER_ID_RE = re.compile(r"(?<![A-Za-z0-9])DD\d{7}(?![A-Za-z0-9])", re.IGNORECASE)
HANDOFF_PROMISE_RE = re.compile(
    r"(已(为您)?转(接)?人工|已转接人工|马上为您转(接)?人工|我帮您转(接)?人工|为您转(接)?人工|工单\s*H\d{8,})"
)
DEFENSIVE_PATTERNS = [
    "不演了", "行，那我直说", "行那我直说", "你爱买不买", "爱要不要",
    "随便你", "这是规定", "你冷静", "我只是AI", "我只是一个AI",
    "这不是我的问题", "你听不懂", "别问了", "烦不烦", "关我什么事",
]
MAX_INPUT_CHARS = 2000


class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("请求过于频繁，请稍后再试")
        self.retry_after = retry_after


class RateLimiter:
    """进程内滑动窗口限流；多实例部署时可换成 Redis。"""

    def __init__(self, limit: int = 40, window_seconds: int = 60) -> None:
        self.limit = max(1, limit)
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] > self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - events[0])) + 1)
                raise RateLimitExceeded(retry_after)
            events.append(now)


def sanitize_input(text: str) -> str:
    text = (text or "").replace("\x00", " ").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_INPUT_CHARS]


def redact_pii(text: str) -> str:
    """用于审计日志，不改变用户实际会话内容。"""
    text = PHONE_RE.sub(lambda m: m.group(1)[:3] + "****" + m.group(1)[-4:], text)
    text = ID_CARD_RE.sub(lambda m: m.group(1) + "********" + m.group(3)[-4:], text)
    text = EMAIL_RE.sub(lambda m: m.group(1) + "***" + m.group(2), text)
    return text


def safe_json(data: Any, limit: int = 8000) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(data)
    return text[:limit]


def truncate_reply(text: str, max_chars: int = 320) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    window = text[: max(20, max_chars - 1)]
    cut = -1
    for punct in ["。", "！", "？", "；", "\n", "，", ",", "."]:
        index = window.rfind(punct)
        if index > cut:
            cut = index
    if cut >= 40:
        return window[: cut + 1].rstrip() + "…"
    return window.rstrip() + "…"


def normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是", "有", "已"}
    return default


def normalize_int(value: Any, default: int = 0, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def clean_arguments(arguments: Dict[str, Any], allowed: Iterable[str]) -> Dict[str, Any]:
    """只保留 schema 声明的字段，避免模型塞入 user_id 等越权参数。"""
    if not isinstance(arguments, dict):
        return {}
    allowed_set = set(allowed)
    return {key: value for key, value in arguments.items() if key in allowed_set and value is not None}


def collect_identifiers(payloads: Iterable[Any]) -> Dict[str, set]:
    text = "\n".join(safe_json(payload) for payload in payloads)
    return {
        "tracking": {item.upper() for item in TRACKING_RE.findall(text)},
        "orders": {item.upper() for item in ORDER_ID_RE.findall(text)},
    }


def sanitize_reply_claims(reply: str, tool_payloads: Iterable[Any]) -> Tuple[str, List[str]]:
    """拦截模型编造的物流单号。

    订单号不做强行替换，因为它可能只是用户输入的回显；
    但物流单号一旦不在工具结果里，基本可以判定是幻觉，直接替换为安全表述。
    """
    allowed = collect_identifiers(tool_payloads)
    warnings: List[str] = []
    if not reply:
        return reply, warnings

    def replace_tracking(match: re.Match) -> str:
        value = match.group(0).upper()
        if value in allowed["tracking"]:
            return match.group(0)
        warnings.append("blocked_unknown_tracking:%s" % value)
        return "以订单页物流为准"

    cleaned = TRACKING_RE.sub(replace_tracking, reply)

    for order_id in ORDER_ID_RE.findall(cleaned):
        if allowed["orders"] and order_id.upper() not in allowed["orders"]:
            warnings.append("unknown_order_id:%s" % order_id)

    return cleaned, warnings


def ensure_handoff_marker(reply: str) -> str:
    if "[转人工]" in reply:
        return reply
    return (reply.rstrip() + "\n[转人工]").strip()


def has_handoff_marker(reply: str) -> bool:
    return "[转人工]" in (reply or "")


def contains_defensive_language(reply: str) -> bool:
    text = (reply or "").lower()
    return any(pattern.lower() in text for pattern in DEFENSIVE_PATTERNS)
