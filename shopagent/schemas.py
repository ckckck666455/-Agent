"""跨模块共享的数据结构。"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EmotionResult:
    level: int = 0
    label: str = "平静"
    score: float = 0.0
    matched: List[str] = field(default_factory=list)
    should_handoff: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IntentResult:
    intent: str = "unknown"
    confidence: float = 0.0
    entities: Dict[str, Any] = field(default_factory=dict)
    secondary: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)

    def as_openai_dict(self) -> Dict[str, Any]:
        import json

        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class LLMResponse:
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    model: str = ""
    finish_reason: str = ""
    raw: Optional[Any] = None


@dataclass
class ToolTrace:
    name: str
    arguments: Dict[str, Any]
    ok: bool
    summary: str = ""
    duration_ms: float = 0.0
    error_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("duration_ms", None)
        return data


@dataclass
class HandoffInfo:
    ticket_id: str
    priority: str
    reason: str
    status: str = "open"
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChatResult:
    reply: str
    session_id: str
    user_id: str
    intent: IntentResult
    emotion: EmotionResult
    tool_calls: List[ToolTrace] = field(default_factory=list)
    handoff: Optional[HandoffInfo] = None
    sources: List[str] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    mode: str = "offline"
    latency_ms: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reply": self.reply,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "intent": self.intent.to_dict(),
            "emotion": self.emotion.to_dict(),
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "handoff": self.handoff.to_dict() if self.handoff else None,
            "sources": list(self.sources),
            "usage": dict(self.usage),
            "mode": self.mode,
            "latency_ms": round(self.latency_ms, 1),
        }
