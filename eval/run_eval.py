"""离线评测：跑固定用例集，输出通过率、工具命中、转人工指标和失败清单。

用法：
    python eval/run_eval.py
    python eval/run_eval.py --limit 10
    python eval/run_eval.py --online   # 用 .env 里的 DeepSeek（会产生费用）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shopagent.agent import ShoppingAgent
from shopagent.config import Settings
from shopagent.guardrails import DEFENSIVE_PATTERNS
from shopagent.storage import Store

# 评测必须与当前日期解耦，否则跨天/CI 会把售后窗口用例跑红。
os.environ.setdefault("DEMO_NOW", "2026-11-04 14:00")


def load_cases(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_case(case: Dict[str, Any], agent: ShoppingAgent) -> Dict[str, Any]:
    user_id = case.get("user_id", "user_001")
    session_id = "eval-" + case["id"]
    tool_names: List[str] = []
    replies: List[str] = []
    handoffs: List[str] = []
    latencies: List[float] = []
    intents: List[str] = []
    errors: List[str] = []

    for message in case.get("turns", []):
        try:
            result = agent.chat(message, session_id=session_id, user_id=user_id)
        except Exception as exc:
            errors.append("exception:%s: %s" % (type(exc).__name__, exc))
            break
        tool_names.extend(trace.name for trace in result.tool_calls)
        replies.append(result.reply)
        intents.append(result.intent.intent)
        latencies.append(result.latency_ms)
        if result.handoff:
            handoffs.append(result.handoff.ticket_id)

    combined = "\n".join(replies)
    failures: List[str] = list(errors)

    for tool in case.get("expected_tools", []):
        if tool not in tool_names:
            failures.append("missing_tool:%s" % tool)
    expected_any = case.get("expected_tools_any", [])
    if expected_any and not any(tool in tool_names for tool in expected_any):
        failures.append("missing_any_tool:%s" % "|".join(expected_any))
    for tool in case.get("forbidden_tools", []):
        if tool in tool_names:
            failures.append("forbidden_tool:%s" % tool)
    for text in case.get("must_include", []):
        if text not in combined:
            failures.append("missing_text:%s" % text)
    if case.get("must_include_any"):
        if not any(text in combined for text in case["must_include_any"]):
            failures.append("missing_any:%s" % "|".join(case["must_include_any"]))
    for text in case.get("must_not_include", []):
        if text in combined:
            failures.append("forbidden_text:%s" % text)
    for phrase in DEFENSIVE_PATTERNS:
        if phrase in combined:
            failures.append("defensive_phrase:%s" % phrase)

    expected_handoff = bool(case.get("expected_handoff", False))
    actual_handoff = bool(handoffs)
    if expected_handoff != actual_handoff:
        failures.append("handoff_expected:%s_actual:%s" % (expected_handoff, actual_handoff))

    return {
        "id": case["id"],
        "category": case.get("category", "未分类"),
        "turns": case.get("turns", []),
        "expected_tools": case.get("expected_tools", []),
        "expected_tools_any": case.get("expected_tools_any", []),
        "tool_names": tool_names,
        "intents": intents,
        "replies": replies,
        "expected_handoff": expected_handoff,
        "actual_handoff": actual_handoff,
        "handoffs": handoffs,
        "latency_ms": round(sum(latencies), 1),
        "failures": failures,
        "passed": not failures,
    }


def build_report(results: List[Dict[str, Any]], mode: str, started: float) -> Dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    tool_cases = [
        item for item in results
        if item["expected_tools"] or item.get("expected_tools_any")
    ]

    def tool_case_ok(item: Dict[str, Any]) -> bool:
        if item["expected_tools"] and not all(tool in item["tool_names"] for tool in item["expected_tools"]):
            return False
        if item.get("expected_tools_any") and not any(tool in item["tool_names"] for tool in item["expected_tools_any"]):
            return False
        return True

    tool_ok = sum(1 for item in tool_cases if tool_case_ok(item))
    tp = sum(1 for item in results if item["expected_handoff"] and item["actual_handoff"])
    fp = sum(1 for item in results if not item["expected_handoff"] and item["actual_handoff"])
    fn = sum(1 for item in results if item["expected_handoff"] and not item["actual_handoff"])
    tn = sum(1 for item in results if not item["expected_handoff"] and not item["actual_handoff"])
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    banned = sum(
        1 for item in results
        for phrase in DEFENSIVE_PATTERNS
        if any(phrase in reply for reply in item["replies"])
    )
    category: Dict[str, Dict[str, int]] = {}
    for item in results:
        bucket = category.setdefault(item["category"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += 1 if item["passed"] else 0
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "tool_cases": len(tool_cases),
        "tool_accuracy": round(tool_ok / len(tool_cases), 4) if tool_cases else 0.0,
        "handoff": {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
        },
        "defensive_phrase_count": banned,
        "avg_latency_ms": round(
            sum(item["latency_ms"] for item in results) / total, 1
        ) if total else 0.0,
        "by_category": category,
        "failures": [item for item in results if not item["passed"]],
    }


def write_report(report: Dict[str, Any], results: List[Dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps({"summary": report, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Agent Evaluation Report",
        "",
        "- 时间：%s" % report["timestamp"],
        "- 模式：%s" % report["mode"],
        "- 用例数：%s" % report["total"],
        "- 通过：%s（%.1f%%）" % (report["passed"], report["pass_rate"] * 100),
        "- 工具命中：%.1f%%（%s 条有工具期望）" % (
            report["tool_accuracy"] * 100, report["tool_cases"]
        ),
        "- 转人工：precision %.1f%%，recall %.1f%%（TP %s / FP %s / FN %s / TN %s）" % (
            report["handoff"]["precision"] * 100,
            report["handoff"]["recall"] * 100,
            report["handoff"]["tp"],
            report["handoff"]["fp"],
            report["handoff"]["fn"],
            report["handoff"]["tn"],
        ),
        "- 防御性话术：%s 处" % report["defensive_phrase_count"],
        "- 平均延迟：%s ms" % report["avg_latency_ms"],
        "",
        "## 分类",
        "",
        "| 分类 | 通过/总数 | 通过率 |",
        "|---|---:|---:|",
    ]
    for name, stats in sorted(report["by_category"].items()):
        rate = stats["passed"] / stats["total"] * 100 if stats["total"] else 0
        lines.append("| %s | %s/%s | %.0f%% |" % (name, stats["passed"], stats["total"], rate))

    lines.extend(["", "## 失败用例", ""])
    failures = report["failures"]
    if not failures:
        lines.append("无。")
    else:
        lines.append("| 用例 | 分类 | 失败原因 | 最后一轮回复 |")
        lines.append("|---|---|---|---|")
        for item in failures:
            reply = (item["replies"][-1] if item["replies"] else "").replace("\n", " ")[:120]
            lines.append(
                "| %s | %s | %s | %s |"
                % (item["id"], item["category"], "；".join(item["failures"]), reply)
            )

    lines.extend([
        "",
        "## 口径",
        "",
        "- 这是规则化离线评测，不是人工语义评分；通过不等于“回答完美”，只代表关键事实/工具/边界满足。",
        "- 支持关键词检查、工具命中、转人工混淆矩阵和防御性话术检查。",
        "- 线上 DeepSeek 评估可用 `python eval/run_eval.py --online`，会产生 API 费用。",
    ])
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="小美 Agent 离线评测")
    parser.add_argument("--online", action="store_true", help="使用 .env 中的 DeepSeek（会产生费用）")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    parser.add_argument("--keep-db", action="store_true", help="保留 runtime/eval.db")
    args = parser.parse_args()

    if not args.online:
        os.environ["LLM_MODE"] = "offline"

    settings = Settings.from_env(ROOT)
    if not args.online:
        settings.offline = True
        settings.api_key = None
    settings.db_path = ROOT / "runtime" / "eval.db"
    settings.rate_limit_per_minute = 1000
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(settings.db_path) + suffix).unlink()
        except FileNotFoundError:
            pass

    cases = load_cases(ROOT / "eval" / "cases.json")
    if args.limit:
        cases = cases[: args.limit]
    store = Store(str(settings.db_path))
    agent = ShoppingAgent(settings=settings, store=store)
    started = time.perf_counter()
    results: List[Dict[str, Any]] = []
    try:
        for index, case in enumerate(cases, 1):
            result = evaluate_case(case, agent)
            results.append(result)
            mark = "PASS" if result["passed"] else "FAIL"
            print("[%02d/%02d] %-4s %s %s" % (index, len(cases), mark, case["id"], case.get("category", "")), flush=True)
    finally:
        agent.close()
        if not args.keep_db:
            for suffix in ("", "-wal", "-shm"):
                try:
                    Path(str(settings.db_path) + suffix).unlink()
                except FileNotFoundError:
                    pass

    report = build_report(results, "offline" if not args.online else "deepseek", started)
    write_report(report, results, ROOT / "eval")
    print("\n=== 结果 ===")
    print("通过：%s/%s（%.1f%%）" % (report["passed"], report["total"], report["pass_rate"] * 100))
    print("工具命中：%.1f%%" % (report["tool_accuracy"] * 100))
    print("转人工 precision/recall：%.1f%% / %.1f%%" % (
        report["handoff"]["precision"] * 100, report["handoff"]["recall"] * 100
    ))
    print("防御性话术：%s 处" % report["defensive_phrase_count"])
    print("报告：eval/report.md")
    if report["failures"]:
        print("\n失败用例：")
        for item in report["failures"]:
            print("- %s %s：%s" % (item["id"], item["category"], "；".join(item["failures"])))
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
