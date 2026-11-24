"""情绪检测：规则打分 + 升级策略。

设计目标不是“理解所有情绪”，而是把高风险投诉稳定地拦在 LLM 之前：
- 命中监管/法律/曝光类词汇：立即转人工（最高优先级）
- 多次表达不满 / 连续负面：升级
- 普通“退款、退货”不误判为愤怒
"""
from __future__ import annotations

import re
from typing import List, Tuple

from .schemas import EmotionResult


# 词组 -> 权重
HIGH_RISK: List[Tuple[str, float]] = [
    ("12315", 5.0),
    ("消协", 4.5),
    ("消费者协会", 4.5),
    ("工商局", 4.5),
    ("市场监管局", 4.5),
    ("起诉", 5.0),
    ("律师", 4.5),
    ("报警", 5.0),
    ("曝光", 4.0),
    ("媒体", 2.5),
    ("投诉", 3.2),
    ("骗子", 4.0),
    ("欺诈", 4.5),
    ("假货", 3.8),
    ("垃圾", 3.0),
    ("气死", 3.2),
    ("维权", 3.2),
    ("差评", 2.4),
    ("退钱", 2.0),
    ("什么破", 2.8),
    ("没人管", 2.6),
    ("说了几遍", 2.6),
    ("说了多少次", 2.8),
    ("第三次", 2.0),
    ("还没解决", 2.4),
    ("一直拖", 2.2),
    ("不处理", 2.2),
]

MEDIUM: List[Tuple[str, float]] = [
    ("太差", 2.0),
    ("很差", 1.8),
    ("失望", 1.3),
    ("无语", 1.8),
    ("离谱", 2.0),
    ("搞什么", 1.8),
    ("烦死", 2.0),
    ("生气", 1.8),
    ("愤怒", 2.0),
    ("不满意", 1.4),
    ("敷衍", 1.8),
    ("推卸", 2.0),
    ("等了", 0.8),
    ("还没", 0.5),
    ("到底", 0.4),
    ("什么服务", 1.8),
    ("我要投诉", 2.0),
    ("什么态度", 2.2),
    ("啥态度", 2.2),
    ("服务态度", 2.2),
    ("会不会服务", 2.2),
    ("就这服务", 2.4),
    ("阴阳怪气", 2.2),
    ("你什么意思", 1.6),
    ("别装了", 1.8),
    ("破店", 2.0),
    ("退款", 1.1),
    ("退货", 0.5),
]

POSITIVE: List[Tuple[str, float]] = [
    ("谢谢", -0.8),
    ("感谢", -0.8),
    ("满意", -1.0),
    ("好用", -0.6),
    ("喜欢", -0.6),
    ("辛苦", -0.5),
    ("不错", -0.5),
    ("好的", -0.3),
]

INTENSIFIERS = ["非常", "特别", "极其", "太", "真的", "已经", "多次", "反复", "一直", "很"]
NEGATION_RE = re.compile(r"(不|没|没有|不是|并非|别|无需|不用)\s*$")

THREAT_RE = re.compile(r"(12315|消协|工商局|市场监管局|起诉|律师|报警|曝光|媒体)")
REPEAT_RE = re.compile(r"(说了几遍|说了多少次|第[一二三四五六七八九十\d]+次|还没解决|一直拖|不处理)")


class EmotionDetector:
    def __init__(self) -> None:
        self.high_risk = HIGH_RISK
        self.medium = MEDIUM
        self.positive = POSITIVE

    @staticmethod
    def _is_negated(text: str, start: int) -> bool:
        window = text[max(0, start - 6):start]
        return bool(NEGATION_RE.search(window))

    def analyze(self, text: str, negative_turns: int = 0) -> EmotionResult:
        text = (text or "").strip()
        if not text:
            return EmotionResult()

        score = 0.0
        matched: List[str] = []

        for keyword, weight in self.high_risk:
            idx = text.find(keyword)
            if idx < 0:
                continue
            if self._is_negated(text, idx):
                score += weight * 0.15
                continue
            score += weight
            matched.append(keyword)

        for keyword, weight in self.medium:
            idx = text.find(keyword)
            if idx < 0:
                continue
            if self._is_negated(text, idx):
                score -= weight * 0.2
                continue
            score += weight
            matched.append(keyword)

        for keyword, weight in self.positive:
            if keyword in text:
                score += weight
                matched.append(keyword)

        # 强烈程度副词会放大负面表达
        if any(word in text for word in INTENSIFIERS) and score > 0:
            score += 0.6

        # 连续负面 / 重复投诉会升级
        if negative_turns >= 1 and score >= 1.0:
            score += 0.5
        if negative_turns >= 2 and score >= 1.0:
            score += 1.5

        # 连续追问、明确威胁单独加权
        if REPEAT_RE.search(text):
            score += 1.0
        threat = bool(THREAT_RE.search(text))

        score = max(0.0, min(10.0, score))

        if threat and score >= 3.0:
            level = 3
            label = "危机"
        elif score >= 4.5:
            level = 2
            label = "愤怒"
        elif score >= 2.0:
            level = 1
            label = "不满"
        else:
            level = 0
            label = "平静"

        should_handoff = level >= 2
        reason = "命中高风险表达：" + "、".join(dict.fromkeys(matched)) if matched else ""
        if threat and not reason:
            reason = "命中监管/法律类威胁表达"

        return EmotionResult(
            level=level,
            label=label,
            score=round(score, 2),
            matched=list(dict.fromkeys(matched)),
            should_handoff=should_handoff,
            reason=reason,
        )

    @staticmethod
    def is_angry(text: str) -> bool:
        return EmotionDetector().analyze(text).should_handoff
