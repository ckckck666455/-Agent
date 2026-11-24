"""多轮记忆：短期窗口裁剪 + 长期摘要 + 用户画像。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .config import Settings
from .nlu import extract_budget, extract_concerns, extract_order_id, extract_skin_type
from .schemas import LLMResponse
from .storage import SessionRecord


CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    ascii_chars = len(ASCII_WORD_RE.findall(text))
    other = max(0, len(text) - cjk - ascii_chars)
    return int(cjk + ascii_chars * 1.3 + other * 0.5) + 1


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += 8
        total += estimate_tokens(str(message.get("content", "")))
        if message.get("tool_calls"):
            total += estimate_tokens(json.dumps(message["tool_calls"], ensure_ascii=False))
    return total


def profile_context(profile: Dict[str, Any]) -> str:
    if not profile:
        return "暂无画像，先通过对话了解买什么、给谁买和预算。"
    parts: List[str] = []
    if profile.get("age_group"):
        parts.append("人群：%s" % profile["age_group"])
    if profile.get("gender"):
        parts.append("性别：%s" % profile["gender"])
    if profile.get("segment"):
        parts.append("标签：%s" % profile["segment"])
    if profile.get("preferred_departments"):
        parts.append("常看：%s" % "、".join(profile["preferred_departments"][:4]))
    if profile.get("skin_type"):
        parts.append("肤质：%s" % profile["skin_type"])
    if profile.get("concerns"):
        parts.append("关注：%s" % "、".join(profile["concerns"][:5]))
    if profile.get("budget"):
        parts.append("预算：%s 元" % profile["budget"])
    if profile.get("allergies"):
        parts.append("过敏/避开：%s" % "、".join(profile["allergies"]))
    if profile.get("member_tier"):
        parts.append("会员：%s（%s 积分）" % (profile["member_tier"], profile.get("points", 0)))
    if profile.get("pregnant"):
        parts.append("处于孕期，需避开高风险成分")
    if profile.get("breastfeeding"):
        parts.append("处于哺乳期，需避开高风险成分")
    return "；".join(parts) if parts else "暂无明确画像。"


def _truncate(text: str, limit: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_rule_based(messages: List[Dict[str, Any]], existing_summary: str = "") -> str:
    """无模型时的兜底摘要：抽取事实和最近诉求，不编造。"""
    user_texts = [
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "user" and message.get("content")
    ]
    if not user_texts and not existing_summary:
        return ""

    facts: List[str] = []
    joined = "\n".join(user_texts)
    skin = extract_skin_type(joined)
    concerns = extract_concerns(joined)
    budget = extract_budget(joined)
    order_id = extract_order_id(joined)
    if skin:
        facts.append("肤质%s" % skin)
    if concerns:
        facts.append("关注%s" % "、".join(concerns[:4]))
    if budget:
        facts.append("预算%s元" % budget)
    if order_id:
        facts.append("涉及订单%s" % order_id)

    recent = "；".join(_truncate(text, 60) for text in user_texts[-4:])
    pieces: List[str] = []
    if existing_summary:
        pieces.append(existing_summary)
    if facts:
        pieces.append("已知信息：" + "，".join(dict.fromkeys(facts)))
    if recent:
        pieces.append("近期诉求：" + recent)
    summary = "。".join(piece for piece in pieces if piece)
    return _truncate(summary, 700)


class MemoryManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def select_history(
        self,
        history: List[Dict[str, Any]],
        max_messages: Optional[int] = None,
        token_budget: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        max_messages = max_messages or self.settings.max_recent_messages
        token_budget = token_budget or self.settings.history_token_budget
        if not history:
            return []

        items = [dict(message) for message in history[-max_messages:] if message.get("role") != "system"]
        # 从一条 user 消息开始，避免出现孤立的 tool 消息导致 API 400
        start = next((i for i, item in enumerate(items) if item.get("role") == "user"), None)
        if start is None:
            return []
        items = items[start:]

        # 旧工具结果只保留摘要，控制上下文
        for item in items[:-4]:
            if item.get("role") == "tool" and len(str(item.get("content", ""))) > 600:
                item["content"] = _truncate(str(item.get("content", "")), 600)

        while items and estimate_messages_tokens(items) > token_budget:
            next_user = next((i for i in range(1, len(items)) if items[i].get("role") == "user"), None)
            if next_user is None:
                break
            items = items[next_user:]
        return items

    def should_compact(self, session: SessionRecord) -> bool:
        total = estimate_messages_tokens(session.history) + estimate_tokens(session.summary)
        return total > self.settings.summary_trigger_tokens and len(session.history) > self.settings.summary_keep_messages

    def compact(
        self,
        session: SessionRecord,
        llm: Optional[Any] = None,
        force: bool = False,
    ) -> bool:
        if not force and not self.should_compact(session):
            return False
        keep = max(2, self.settings.summary_keep_messages)
        older = session.history[:-keep]
        tail = session.history[-keep:]
        # 保证尾部从 user 开始
        start = next((i for i, item in enumerate(tail) if item.get("role") == "user"), 0)
        tail = tail[start:]
        if not older:
            return False

        summary = ""
        if llm is not None and not getattr(llm, "is_mock", False):
            summary = self._summarize_with_llm(llm, older, session.summary)
        if not summary:
            summary = summarize_rule_based(older, session.summary)

        session.summary = _truncate(summary, 800)
        session.history = tail
        session.state["compactions"] = int(session.state.get("compactions", 0)) + 1
        return True

    def _summarize_with_llm(
        self,
        llm: Any,
        messages: List[Dict[str, Any]],
        existing_summary: str,
    ) -> str:
        transcript_lines: List[str] = []
        for message in messages[-30:]:
            role = message.get("role")
            content = _truncate(str(message.get("content", "")), 220)
            if role == "user":
                transcript_lines.append("用户：" + content)
            elif role == "assistant" and content:
                transcript_lines.append("客服：" + content)
            elif role == "tool":
                transcript_lines.append("工具结果：" + content[:180])
        prompt = (
            "请把下面的电商客服对话压缩成不超过 220 字的中文摘要，供后续对话使用。\n"
            "必须保留：用户肤质/预算/核心诉求、涉及的订单或商品、已经做出的承诺、尚未解决的问题。\n"
            "不要编造对话中没有的信息，不要输出分析过程，只输出摘要。\n\n"
            "已有摘要：%s\n\n对话：\n%s"
            % (existing_summary or "无", "\n".join(transcript_lines))
        )
        try:
            response: LLMResponse = llm.chat(
                [
                    {"role": "system", "content": "你是对话摘要器，只输出简洁、事实准确的中文摘要。"},
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                temperature=0.2,
                max_tokens=320,
            )
            text = (response.content or "").strip()
            # 主模型失败时 ResilientLLM 会降级到规则引擎；规则引擎不适合做摘要，
            # 此时返回空串，让上层使用 summarize_rule_based。
            if not text or "不太确定" in text or len(text) < 12:
                return ""
            return text
        except Exception:
            return ""

    def build_system_context(self, profile: Dict[str, Any], summary: str) -> str:
        lines = ["【用户画像】" + profile_context(profile)]
        if summary:
            lines.append("【历史摘要】" + summary)
        return "\n".join(lines)
