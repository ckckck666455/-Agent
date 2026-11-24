"""知识库检索：优先使用 TF-IDF 向量索引，缺少 sklearn 时回退到字符 n-gram。

TF-IDF 的 char(1,2) 向量对中文短查询足够稳，且不需要额外模型/API；
生产环境可以把 `backend` 换成 bge-m3 / text-embedding-3-small + pgvector，
`search(query) -> matches` 接口保持不变。
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # 生产可选依赖；缺失时仍有纯 Python 回退
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    _HAS_SKLEARN = True
except ImportError:  # pragma: no cover
    TfidfVectorizer = None  # type: ignore
    cosine_similarity = None  # type: ignore
    _HAS_SKLEARN = False


CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
WORD_RE = re.compile(r"[a-zA-Z0-9%+]+")
PUNCT_RE = re.compile(r"[^\u4e00-\u9fffa-zA-Z0-9%+]+")

SAFETY_TERMS = ["过敏", "红肿", "刺痛", "瘙痒", "渗液", "不良反应", "烂脸", "爆痘", "就医", "医生"]


def tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    tokens: List[str] = []
    for segment in CJK_RE.findall(text):
        if len(segment) == 1:
            tokens.append(segment)
            continue
        # 单字 + 二元组：短查询召回更好，二元组保证精度
        tokens.extend(list(segment))
        tokens.extend(segment[i:i + 2] for i in range(len(segment) - 1))
    tokens.extend(WORD_RE.findall(text))
    return tokens


@dataclass
class FAQEntry:
    id: str
    category: str
    question: str
    answer: str
    keywords: List[str] = field(default_factory=list)
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FAQEntry":
        return cls(
            id=str(data.get("id", "")),
            category=str(data.get("category", "")),
            question=str(data.get("question", "")),
            answer=str(data.get("answer", "")),
            keywords=list(data.get("keywords", []) or []),
            updated_at=str(data.get("updated_at", "")),
        )


@dataclass
class FAQMatch:
    entry: FAQEntry
    score: float
    matched_terms: List[str] = field(default_factory=list)


class KnowledgeBase:
    def __init__(self, entries: List[FAQEntry]) -> None:
        self.entries = entries
        self._doc_tokens: List[Counter] = []
        self._df: Counter = Counter()
        self._idf: Dict[str, float] = {}
        self._tfidf: Optional[Any] = None
        self._matrix: Optional[Any] = None
        self.backend = "char-ngram"
        self._build_index()

    @classmethod
    def from_json(cls, path: Path) -> "KnowledgeBase":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([FAQEntry.from_dict(item) for item in data])

    def _document_text(self, entry: FAQEntry) -> str:
        return " ".join([entry.question, entry.answer, entry.category, " ".join(entry.keywords)])

    def _build_index(self) -> None:
        texts = [self._document_text(entry) for entry in self.entries]
        if _HAS_SKLEARN and texts:
            self._tfidf = TfidfVectorizer(
                analyzer="char",
                ngram_range=(1, 2),
                min_df=1,
                sublinear_tf=True,
                norm="l2",
            )
            self._matrix = self._tfidf.fit_transform(texts)
            self.backend = "tfidf-char-vector"
            return
        # 纯 Python 回退：字符 unigram + bigram + IDF
        for text in texts:
            counter = Counter(tokenize(text))
            self._doc_tokens.append(counter)
            for token in counter:
                self._df[token] += 1
        total = max(1, len(self.entries))
        self._idf = {
            token: math.log((total + 1) / (df + 1)) + 1.0
            for token, df in self._df.items()
        }

    def _vector(self, counter: Counter) -> Dict[str, float]:
        return {
            token: (1.0 + math.log(count)) * self._idf.get(token, 1.0)
            for token, count in counter.items()
        }

    @staticmethod
    def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(value * b.get(token, 0.0) for token, value in a.items())
        norm_a = math.sqrt(sum(value * value for value in a.values()))
        norm_b = math.sqrt(sum(value * value for value in b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def search(self, query: str, top_k: int = 3, min_score: float = 0.12) -> List[FAQMatch]:
        query = (query or "").strip()
        if not query:
            return []
        lowered = query.lower()
        safety_query = any(term in lowered for term in SAFETY_TERMS)
        if self._tfidf is not None and self._matrix is not None:
            query_vec = self._tfidf.transform([query])
            similarities = cosine_similarity(query_vec, self._matrix)[0]
            base_scores = [float(value) for value in similarities]
        else:
            query_counter = Counter(tokenize(query))
            query_vec = self._vector(query_counter)
            base_scores = [
                self._cosine(query_vec, self._vector(self._doc_tokens[index]))
                for index in range(len(self.entries))
            ]

        results: List[FAQMatch] = []
        for index, entry in enumerate(self.entries):
            score = base_scores[index]
            matched: List[str] = []
            for keyword in entry.keywords:
                if keyword.lower() in lowered:
                    score += 0.18
                    matched.append(keyword)
            if entry.category and entry.category.lower() in lowered:
                score += 0.10
            # 安全类问题优先给“过敏处理/孕妇/儿童”等条目，避免被“拆封退货”抢走
            if safety_query and entry.category == "安全":
                score += 0.35
            if "过敏" in lowered and entry.id == "FAQ005":
                score += 0.25
            if score >= min_score:
                results.append(FAQMatch(entry=entry, score=round(score, 4), matched_terms=matched))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def format_context(self, matches: List[FAQMatch], max_chars: int = 900) -> str:
        chunks: List[str] = []
        used = 0
        for match in matches:
            entry = match.entry
            chunk = "【%s】%s\n答：%s" % (entry.category, entry.question, entry.answer)
            if used + len(chunk) > max_chars:
                break
            chunks.append(chunk)
            used += len(chunk)
        return "\n\n".join(chunks)

    def get(self, faq_id: str) -> Optional[FAQEntry]:
        for entry in self.entries:
            if entry.id == faq_id:
                return entry
        return None

    def all_categories(self) -> List[str]:
        return sorted({entry.category for entry in self.entries})
