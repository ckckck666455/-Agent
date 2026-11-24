"""轻量并发压测：不依赖 Locust，便于在本机快速出报告。

用法：
  python run_api.py --port 8010 --offline
  python loadtest/run_load.py --url http://127.0.0.1:8010 --requests 200 --concurrency 20
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

import requests

ROOT = Path(__file__).resolve().parents[1]
_THREAD_LOCAL = threading.local()
MESSAGES = [
    "你们卖什么",
    "给老人买一双防滑鞋，预算300以内",
    "给5岁孩子买点零食，要安全一点",
    "给男士买一件通勤纯棉衬衫，XL",
    "我是油皮，想买300以内的面霜",
    "帮我查订单 DD2026001 到哪了",
    "哪个商品退货率高",
    "最近活动 ROI 怎么样",
    "你啥态度",
]


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * p))
    return round(ordered[index], 1)


def _session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        _THREAD_LOCAL.session = session
    return session


def one_request(url: str, timeout: float) -> Dict[str, Any]:
    started = time.perf_counter()
    payload = {
        "message": random.choice(MESSAGES),
        "session_id": "load-" + uuid.uuid4().hex[:12],
        # 压测用独立用户，避免把限流误判成系统错误
        "user_id": "load-user-" + uuid.uuid4().hex[:10],
    }
    try:
        response = _session().post(url.rstrip("/") + "/api/chat", json=payload, timeout=timeout)
        latency = (time.perf_counter() - started) * 1000
        return {
            "status": response.status_code,
            "latency_ms": latency,
            "ok": response.status_code == 200 and bool(response.json().get("reply")),
        }
    except Exception as exc:
        return {
            "status": 0,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "ok": False,
            "error": type(exc).__name__,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    started = time.perf_counter()
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(one_request, args.url, args.timeout)
            for _ in range(args.requests)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    elapsed = time.perf_counter() - started

    latencies = [item["latency_ms"] for item in results]
    errors = [item for item in results if not item["ok"]]
    summary = {
        "url": args.url,
        "requests": len(results),
        "concurrency": args.concurrency,
        "elapsed_seconds": round(elapsed, 2),
        "rps": round(len(results) / elapsed, 2) if elapsed else 0.0,
        "errors": len(errors),
        "error_rate": round(len(errors) / len(results), 4) if results else 0.0,
        "avg_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "max_ms": round(max(latencies), 1) if latencies else 0.0,
    }
    out_dir = ROOT / "loadtest"
    (out_dir / "report.json").write_text(
        json.dumps({"summary": summary, "errors": errors}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Load Test Report",
        "",
        "- 目标：`%s`" % args.url,
        "- 模式：离线（MockLLM，避免 API 费用）",
        "- 请求数：%s，并发：%s" % (summary["requests"], summary["concurrency"]),
        "- 总耗时：%ss，RPS：%s" % (summary["elapsed_seconds"], summary["rps"]),
        "- 错误数：%s（%.2f%%）" % (summary["errors"], summary["error_rate"] * 100),
        "- 平均：%s ms" % summary["avg_ms"],
        "- P50：%s ms，P95：%s ms，P99：%s ms" % (
            summary["p50_ms"], summary["p95_ms"], summary["p99_ms"]
        ),
        "",
        "> 这是离线规则引擎压测，反映编排/HTTP/DB 开销，不代表 DeepSeek 线上延迟。",
    ]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
