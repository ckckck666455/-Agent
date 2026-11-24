"""RAG 检索评测：Hit@1 / Hit@3 / MRR。

用法：python eval/rag_eval.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shopagent.knowledge import KnowledgeBase


QUERIES = [
    ("是正品吗，支持专柜验货吗", "FAQ006"),
    ("下单后多久发货", "FAQ001"),
    ("怎么查物流到哪了", "FAQ002"),
    ("支持七天无理由退货吗", "FAQ003"),
    ("拆封了还能退吗", "FAQ004"),
    ("用完后过敏怎么办", "FAQ005"),
    ("孕妇可以用吗", "FAQ007"),
    ("优惠券可以叠加吗", "FAQ008"),
    ("会员积分怎么算", "FAQ009"),
    ("可以开发票吗", "FAQ010"),
    ("支持哪些支付方式", "FAQ011"),
    ("配送到哪些地区", "FAQ012"),
    ("买完降价了能补差价吗", "FAQ013"),
    ("人工客服几点在线", "FAQ014"),
    ("退货流程是什么", "FAQ015"),
    ("退款多久到账", "FAQ016"),
    ("小样和赠品有售后吗", "FAQ017"),
    ("怎么查防伪", "FAQ018"),
    ("敏感肌怎么先测试", "FAQ019"),
    ("保质期和开封后能用多久", "FAQ020"),
    ("可以修改收货地址吗", "FAQ021"),
    ("怎么取消订单", "FAQ022"),
    ("对处理结果不满意怎么投诉", "FAQ023"),
    ("儿童可以用吗", "FAQ024"),
    ("护肤品能治疗皮肤病吗", "FAQ025"),
]


def main() -> int:
    kb = KnowledgeBase.from_json(ROOT / "data" / "faqs.json")
    rows = []
    hits1 = 0
    hits3 = 0
    reciprocal_rank = 0.0
    for query, expected in QUERIES:
        matches = kb.search(query, top_k=3, min_score=0.0)
        ids = [match.entry.id for match in matches]
        rank = ids.index(expected) + 1 if expected in ids else 0
        hits1 += 1 if rank == 1 else 0
        hits3 += 1 if 1 <= rank <= 3 else 0
        reciprocal_rank += 1.0 / rank if rank else 0.0
        rows.append({
            "query": query,
            "expected": expected,
            "returned": ids,
            "rank": rank,
            "top_score": matches[0].score if matches else 0.0,
        })

    total = len(QUERIES)
    summary = {
        "backend": kb.backend,
        "queries": total,
        "hit_at_1": round(hits1 / total, 4),
        "hit_at_3": round(hits3 / total, 4),
        "mrr": round(reciprocal_rank / total, 4),
        "failures": [row for row in rows if row["rank"] != 1],
    }
    (ROOT / "eval" / "rag_report.json").write_text(
        json.dumps({"summary": summary, "results": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# RAG Retrieval Report",
        "",
        "- 检索后端：`%s`" % summary["backend"],
        "- 查询数：%s" % total,
        "- Hit@1：%.1f%%" % (summary["hit_at_1"] * 100),
        "- Hit@3：%.1f%%" % (summary["hit_at_3"] * 100),
        "- MRR：%.4f" % summary["mrr"],
        "",
        "| 查询 | 期望 | 返回 | 首次命中排名 | Top score |",
        "|---|---|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| %s | %s | %s | %s | %.3f |"
            % (row["query"], row["expected"], "、".join(row["returned"]), row["rank"] or "-", row["top_score"])
        )
    lines.extend([
        "",
        "## 口径",
        "",
        "- 这是检索评测，不评估生成话术；Hit@1 表示正确答案排第一。",
        "- 当前是 TF-IDF 字符向量基线，可替换成 bge-m3 / text-embedding-3-small + pgvector。",
    ])
    (ROOT / "eval" / "rag_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("backend:", summary["backend"])
    print("Hit@1: %.1f%%  Hit@3: %.1f%%  MRR: %.4f" % (
        summary["hit_at_1"] * 100, summary["hit_at_3"] * 100, summary["mrr"]
    ))
    print("failures:", [row["query"] for row in summary["failures"]])
    print("report: eval/rag_report.md")
    return 0 if not summary["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
