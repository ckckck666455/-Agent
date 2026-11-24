"""Agent 编排层：输入护栏 → 情绪分流 → 记忆 → LLM/工具循环 → 输出护栏 → 持久化。"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .emotion import EmotionDetector
from .guardrails import (
    HANDOFF_PROMISE_RE,
    RateLimiter,
    RateLimitExceeded,
    contains_defensive_language,
    ensure_handoff_marker,
    has_handoff_marker,
    redact_pii,
    sanitize_input,
    sanitize_reply_claims,
    truncate_reply,
)
from .knowledge import KnowledgeBase
from .llm import build_llm
from .memory import MemoryManager, estimate_tokens
from .nlu import NLU
from .prompts import build_system_prompt
from .schemas import ChatResult, EmotionResult, HandoffInfo, IntentResult, ToolTrace
from .storage import SessionRecord, Store, now_iso
from .tools import CommerceToolkit, ToolContext


logger = logging.getLogger(__name__)

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SessionOwnershipError(PermissionError):
    pass


class ShoppingAgent:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        store: Optional[Store] = None,
        llm: Optional[Any] = None,
        knowledge: Optional[KnowledgeBase] = None,
        toolkit: Optional[CommerceToolkit] = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.store = store or Store(str(self.settings.db_path))
        self.knowledge = knowledge or KnowledgeBase.from_json(self.settings.data_dir / "faqs.json")
        self.toolkit = toolkit or CommerceToolkit(self.settings, self.store, self.knowledge)
        self.nlu = NLU(self.toolkit.products)
        self.llm = llm or build_llm(self.settings)
        self.emotion = EmotionDetector()
        self.memory = MemoryManager(self.settings)
        self.rate_limiter = RateLimiter(self.settings.rate_limit_per_minute)
        self._closed = False

    @property
    def mode(self) -> str:
        if getattr(self.llm, "is_mock", False):
            return "offline"
        if getattr(self.llm, "used_fallback", False):
            return "deepseek_fallback"
        return "deepseek"

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        user_id: str = "user_001",
    ) -> ChatResult:
        start = time.perf_counter()
        text = sanitize_input(message)
        if not text:
            raise ValueError("消息不能为空")
        if not USER_ID_RE.match(user_id or ""):
            raise ValueError("user_id 只能包含字母、数字、下划线和短横线")
        self.rate_limiter.check(user_id)

        session_id = session_id or ("S" + uuid.uuid4().hex[:14])
        if not SESSION_ID_RE.match(session_id):
            raise ValueError("session_id 只能包含字母、数字、下划线和短横线")
        session = self.store.get_or_create_session(session_id, user_id)
        if session.user_id != user_id:
            raise SessionOwnershipError("该会话不属于当前用户")

        profile = self.toolkit.get_profile(user_id)
        intent = self.nlu.classify(text)
        emotion = self.emotion.analyze(
            text,
            negative_turns=int(session.state.get("negative_turns", 0) or 0),
        )

        # 用户主动提供肤质/预算/过敏信息时，写入长期画像
        updates = self.nlu.extract_profile_facts(text, profile)
        if updates:
            for key, value in updates.items():
                profile[key] = value
            self.store.save_profile(user_id, profile)
            self.store.log_event(
                "profile_updated",
                user_id=user_id,
                session_id=session_id,
                payload={"fields": list(updates.keys())},
            )

        session.history.append({"role": "user", "content": text})
        self.store.log_event(
            "user_message",
            user_id=user_id,
            session_id=session_id,
            payload={
                "text": redact_pii(text)[:500],
                "intent": intent.intent,
                "emotion": emotion.to_dict(),
                "mode": self.mode,
            },
        )

        # 1. 高风险情绪：不调模型，直接建单转人工
        # 情绪安全阀优先于其他规则：即使用户同时夹带注入指令，也先处理投诉。
        if emotion.should_handoff:
            handoff = self._ensure_handoff(
                session,
                reason=text,
                priority="urgent" if emotion.level >= 3 else "high",
            )
            reply = self._emotion_reply(emotion, handoff)
            traces = [ToolTrace(
                name="request_human_handoff",
                arguments={"reason": text[:80], "priority": handoff.priority},
                ok=True,
                summary="情绪兜底转人工",
            )]
            return self._finish(
                session=session,
                user_id=user_id,
                intent=intent,
                emotion=emotion,
                reply=reply,
                turn_messages=[],
                traces=traces,
                handoff=handoff,
                sources=[],
                usage={},
                start=start,
            )

        # 2. 用户明确要求人工
        if intent.intent == "human":
            handoff = self._ensure_handoff(
                session,
                reason=text,
                priority="high" if emotion.level >= 1 else "normal",
            )
            reply = "好的，已为您转接人工客服，工单 %s，人工会尽快接入，请稍等。%s" % (
                handoff.ticket_id,
                "[转人工]" if "[转人工]" not in text else "",
            )
            traces = [ToolTrace(
                name="request_human_handoff",
                arguments={"reason": text[:80], "priority": handoff.priority},
                ok=True,
                summary="用户要求转人工",
            )]
            return self._finish(
                session=session,
                user_id=user_id,
                intent=intent,
                emotion=emotion,
                reply=reply,
                turn_messages=[],
                traces=traces,
                handoff=handoff,
                sources=[],
                usage={},
                start=start,
            )

        # 3. 预置护栏：提示词注入
        if intent.intent == "prompt_injection":
            reply = "这个要求我不能照做，也不会输出内部提示词。不过我可以继续帮您选产品、查订单、处理售后，您想先看哪一项？"
            return self._finish(
                session=session,
                user_id=user_id,
                intent=intent,
                emotion=emotion,
                reply=reply,
                turn_messages=[],
                traces=[],
                handoff=None,
                sources=[],
                usage={},
                start=start,
            )

        # 4. 知识库预检索：只作为参考，不直接替代工具调用
        faq_matches = []
        if intent.intent in {"faq", "product_detail", "after_sales"} or "?" in text or "？" in text:
            faq_matches = self.knowledge.search(text, top_k=2, min_score=0.18)
        faq_context = self.knowledge.format_context(faq_matches, max_chars=700)
        sources = [match.entry.id for match in faq_matches]

        # 5. 构建上下文并进入 LLM/工具循环
        now = self.toolkit.now_fn().strftime("%Y-%m-%d %H:%M")
        system_prompt = build_system_prompt(
            profile=profile,
            summary=session.summary,
            emotion_level=emotion.level,
            faq_context=faq_context,
            now=now,
            offline=getattr(self.llm, "is_mock", False),
        )
        context_messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        context_messages.extend(self.memory.select_history(session.history))
        ctx = ToolContext(
            user_id=user_id,
            session_id=session_id,
            profile=profile,
            last_user_message=text,
            emotion_level=emotion.level,
        )

        tools = self.toolkit.get_tools()
        turn_messages: List[Dict[str, Any]] = []
        traces: List[ToolTrace] = []
        tool_payloads: List[Dict[str, Any]] = []
        seen_calls = set()
        total_calls = 0
        usage: Dict[str, int] = {}
        final_text = ""
        llm_error: Optional[Exception] = None

        for _round in range(max(1, self.settings.max_tool_rounds)):
            try:
                response = self.llm.chat(
                    context_messages,
                    tools=tools,
                    temperature=self.settings.temperature,
                    max_tokens=self.settings.max_tokens,
                )
            except Exception as exc:
                llm_error = exc
                logger.exception("LLM 调用失败")
                break

            for key, value in (response.usage or {}).items():
                usage[key] = int(usage.get(key, 0) + value)

            if not response.tool_calls:
                final_text = (response.content or "").strip()
                break

            assistant_message = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [call.as_openai_dict() for call in response.tool_calls],
            }
            context_messages.append(assistant_message)
            turn_messages.append(assistant_message)

            for call in response.tool_calls:
                total_calls += 1
                signature = "%s:%s" % (
                    call.name,
                    json.dumps(call.arguments, ensure_ascii=False, sort_keys=True, default=str),
                )
                if total_calls > self.settings.max_tool_calls:
                    result = {
                        "ok": False,
                        "tool": call.name,
                        "error_code": "TOOL_BUDGET_EXCEEDED",
                        "message": "本轮工具调用次数已达上限，请基于已有信息直接回答。",
                        "data": {},
                    }
                elif signature in seen_calls:
                    result = {
                        "ok": False,
                        "tool": call.name,
                        "error_code": "DUPLICATE_TOOL_CALL",
                        "message": "重复的工具调用已跳过，请使用已有结果。",
                        "data": {},
                    }
                else:
                    seen_calls.add(signature)
                    result = self.toolkit.execute(call.name, call.arguments, ctx)
                    if result.get("ok") and call.name == "update_user_profile":
                        ctx.profile = result.get("data") or ctx.profile

                payload_text = json.dumps(result, ensure_ascii=False, default=str)
                tool_message = {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": payload_text,
                }
                context_messages.append(tool_message)
                turn_messages.append(tool_message)
                tool_payloads.append(result)
                traces.append(ToolTrace(
                    name=call.name,
                    arguments=call.arguments,
                    ok=bool(result.get("ok")),
                    summary=str(result.get("message", ""))[:160],
                    duration_ms=float(result.get("duration_ms", 0) or 0),
                    error_code=str(result.get("error_code", "") or ""),
                ))

        if not final_text:
            if tool_payloads:
                final_text = self._fallback_from_tools(tool_payloads)
            elif llm_error:
                final_text = "抱歉，我这边查询服务暂时不稳定。您可以稍后重试，或告诉我“转人工”，我帮您接入人工客服。"
            else:
                final_text = "我这边没有拿到有效结果，您可以换个说法，或我帮您转人工确认。"

        for payload in tool_payloads:
            if payload.get("tool") == "search_faq" and payload.get("ok"):
                sources.extend((payload.get("data") or {}).get("sources") or [])
        sources = list(dict.fromkeys(sources))

        reply, handoff = self._postprocess(
            text=text,
            reply=final_text,
            tool_payloads=tool_payloads,
            emotion=emotion,
            session=session,
        )

        return self._finish(
            session=session,
            user_id=user_id,
            intent=intent,
            emotion=emotion,
            reply=reply,
            turn_messages=turn_messages,
            traces=traces,
            handoff=handoff,
            sources=sources,
            usage=usage,
            start=start,
        )

    # ------------------------------------------------------------------
    # 结束一轮
    # ------------------------------------------------------------------
    def _finish(
        self,
        session: SessionRecord,
        user_id: str,
        intent: IntentResult,
        emotion: EmotionResult,
        reply: str,
        turn_messages: List[Dict[str, Any]],
        traces: List[ToolTrace],
        handoff: Optional[HandoffInfo],
        sources: List[str],
        usage: Dict[str, int],
        start: float,
    ) -> ChatResult:
        reply = truncate_reply(reply, self.settings.max_reply_chars)
        if handoff:
            reply = ensure_handoff_marker(reply)
            if handoff.ticket_id and handoff.ticket_id not in reply:
                reply = reply.replace("[转人工]", "（工单 %s）[转人工]" % handoff.ticket_id)

        final_message = {"role": "assistant", "content": reply}
        turn_messages.append(final_message)
        session.history.extend(turn_messages)
        session.state["turns"] = int(session.state.get("turns", 0) or 0) + 1
        session.state["last_intent"] = intent.intent
        session.state["last_emotion"] = emotion.level
        session.state["negative_turns"] = (
            int(session.state.get("negative_turns", 0) or 0) + 1 if emotion.level >= 1 else 0
        )
        session.state["last_tool_calls"] = [trace.name for trace in traces]
        if handoff:
            session.state["handoff_ticket"] = handoff.ticket_id

        try:
            self.memory.compact(session, self.llm)
        except Exception:
            logger.exception("记忆压缩失败，保留原始历史")

        self.store.save_session(session)
        self.store.log_event(
            "assistant_message",
            user_id=user_id,
            session_id=session.session_id,
            payload={
                "reply": redact_pii(reply)[:800],
                "intent": intent.intent,
                "emotion": emotion.level,
                "tools": [trace.name for trace in traces],
                "handoff": handoff.ticket_id if handoff else None,
                "mode": self.mode,
            },
        )
        latency_ms = (time.perf_counter() - start) * 1000
        return ChatResult(
            reply=reply,
            session_id=session.session_id,
            user_id=user_id,
            intent=intent,
            emotion=emotion,
            tool_calls=traces,
            handoff=handoff,
            sources=sources,
            usage=usage,
            mode=self.mode,
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------
    # 输出处理
    # ------------------------------------------------------------------
    def _postprocess(
        self,
        text: str,
        reply: str,
        tool_payloads: List[Dict[str, Any]],
        emotion: EmotionResult,
        session: SessionRecord,
    ) -> Tuple[str, Optional[HandoffInfo]]:
        reply = (reply or "").strip()
        reply, claim_warnings = sanitize_reply_claims(reply, tool_payloads)
        if claim_warnings:
            self.store.log_event(
                "claim_guard",
                user_id=session.user_id,
                session_id=session.session_id,
                payload={"warnings": claim_warnings},
            )

        if contains_defensive_language(reply):
            self.store.log_event(
                "tone_guard",
                user_id=session.user_id,
                session_id=session.session_id,
                payload={"reason": "defensive_language"},
            )
            reply = (
                "抱歉，刚才我的表达让您不舒服了，是我没处理好。"
                "您先不用重复，我按您说的来：您是想退货、换货、补偿，还是先查订单？"
            )

        handoff: Optional[HandoffInfo] = None
        for payload in tool_payloads:
            if payload.get("tool") == "request_human_handoff" and payload.get("ok"):
                data = payload.get("data") or {}
                handoff = HandoffInfo(
                    ticket_id=str(data.get("ticket_id", "")),
                    priority=str(data.get("priority", "normal")),
                    reason=str(data.get("reason") or text[:80]),
                    status=str(data.get("status", "open")),
                    created_at=str(data.get("created_at", "")),
                )
                break

        # 模型说“已转人工”但没有真正建单：补齐工单，避免空头承诺。
        # 注意只匹配明确的完成态，不能把“可以转人工/需要我帮您转吗”误判成已转接。
        if handoff is None and (has_handoff_marker(reply) or HANDOFF_PROMISE_RE.search(reply)):
            handoff = self._ensure_handoff(
                session,
                reason=text,
                priority="high" if emotion.level >= 1 else "normal",
            )

        if handoff:
            reply = ensure_handoff_marker(reply)
            if handoff.ticket_id and handoff.ticket_id not in reply:
                reply = reply.replace("[转人工]", "工单 %s。[转人工]" % handoff.ticket_id)

        if emotion.level == 1 and not any(word in reply for word in ["抱歉", "不好意思", "理解", "添麻烦"]):
            reply = "抱歉让您有不好的体验。" + reply

        return reply, handoff

    @staticmethod
    def _fallback_from_tools(tool_payloads: List[Dict[str, Any]]) -> str:
        for payload in reversed(tool_payloads):
            if not payload.get("ok"):
                continue
            name = payload.get("tool")
            data = payload.get("data") or {}
            if name == "search_products":
                products = data.get("products") or []
                if products:
                    product = products[0]
                    return "我查到「%s」，¥%s，库存 %s 件。需要我帮您看详情或加购吗？" % (
                        product.get("name"), product.get("price"), product.get("stock")
                    )
            if name == "query_order":
                return "订单 %s 当前「%s」，实付 ¥%s。需要我继续查物流或售后吗？" % (
                    data.get("order_id"), data.get("status"), data.get("paid")
                )
            if payload.get("message"):
                return str(payload["message"])
        return "我这边暂时没有拿到有效结果，您可以换个说法，或我帮您转人工确认。"

    def _emotion_reply(self, emotion: EmotionResult, handoff: HandoffInfo) -> str:
        if emotion.level >= 3:
            return (
                "非常抱歉给您带来这么差的体验，您反馈的问题我已经记录，并会一并转给人工。"
                "已为您转接人工客服，工单 %s，会优先处理。[转人工]" % handoff.ticket_id
            )
        return (
            "很抱歉让您有不好的体验。我先停止推荐，已为您转接人工客服，工单 %s，"
            "人工会尽快接入处理。[转人工]" % handoff.ticket_id
        )

    # ------------------------------------------------------------------
    # 转人工
    # ------------------------------------------------------------------
    def _ensure_handoff(self, session: SessionRecord, reason: str, priority: str = "normal") -> HandoffInfo:
        existing = self.store.get_open_handoff(session.session_id)
        if existing:
            return HandoffInfo(
                ticket_id=existing["ticket_id"],
                priority=existing.get("priority", "normal"),
                reason=existing.get("reason", reason),
                status=existing.get("status", "open"),
                created_at=existing.get("created_at", ""),
            )

        if priority not in {"normal", "high", "urgent"}:
            priority = "normal"
        ticket_id = "H%s%s" % (self.toolkit.now_fn().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:4].upper())
        recent = [
            redact_pii(str(message.get("content", "")))[:160]
            for message in session.history
            if message.get("role") == "user"
        ][-4:]
        record = self.store.create_handoff(
            ticket_id=ticket_id,
            session_id=session.session_id,
            user_id=session.user_id,
            reason=reason[:300],
            priority=priority,
            context={
                "summary": session.summary,
                "recent_user_messages": recent,
                "last_intent": session.state.get("last_intent", ""),
                "emotion": session.state.get("last_emotion", 0),
            },
        )
        self.store.log_event(
            "handoff_created",
            user_id=session.user_id,
            session_id=session.session_id,
            payload={"ticket_id": ticket_id, "priority": priority, "reason": reason[:200]},
        )
        session.state["handoff_ticket"] = ticket_id
        return HandoffInfo(
            ticket_id=ticket_id,
            priority=priority,
            reason=reason[:300],
            status="open",
            created_at=record.get("created_at", now_iso()),
        )

    # ------------------------------------------------------------------
    # 会话管理 / 健康检查
    # ------------------------------------------------------------------
    def get_session_history(self, session_id: str, user_id: str) -> List[Dict[str, Any]]:
        session = self.store.get_session(session_id)
        if not session:
            raise KeyError("会话不存在")
        if session.user_id != user_id:
            raise SessionOwnershipError("该会话不属于当前用户")
        history = []
        for message in session.history:
            role = message.get("role")
            if role == "system":
                continue
            entry: Dict[str, Any] = {
                "role": role,
                "content": str(message.get("content", ""))[:1200],
            }
            if role == "tool":
                entry["content"] = entry["content"][:500]
            history.append(entry)
        return history

    def reset_session(self, session_id: str, user_id: str) -> bool:
        session = self.store.get_session(session_id)
        if not session:
            return False
        if session.user_id != user_id:
            raise SessionOwnershipError("该会话不属于当前用户")
        self.store.delete_session(session_id)
        self.store.log_event("session_reset", user_id=user_id, session_id=session_id)
        return True

    def get_profile(self, user_id: str) -> Dict[str, Any]:
        return self.toolkit.get_profile(user_id)

    def update_profile(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        ctx = ToolContext(user_id=user_id, session_id="profile_api", profile=self.toolkit.get_profile(user_id))
        result = self.toolkit.execute("update_user_profile", updates, ctx)
        if not result.get("ok"):
            raise ValueError(result.get("message", "画像更新失败"))
        return result.get("data") or {}

    def health(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "mode": self.mode,
            "model": getattr(self.llm, "model_name", ""),
            "has_api_key": bool(self.settings.api_key),
            "products": len(self.toolkit.products),
            "faqs": len(self.knowledge.entries),
            "patterns": {
                "shop": "澄研美妆旗舰店",
                "max_tool_rounds": self.settings.max_tool_rounds,
                "max_tool_calls": self.settings.max_tool_calls,
                "return_window_days": self.settings.return_window_days,
                "coupon_max_amount": self.settings.coupon_max_amount,
            },
            "stats": self.store.stats(),
        }

    def close(self) -> None:
        if not self._closed:
            try:
                self.toolkit.close()
            except Exception:
                logger.exception("关闭 ERP 客户端失败")
            self.store.close()
            self._closed = True
