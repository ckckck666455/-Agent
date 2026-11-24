"""进程内指标：请求数、错误率、平均延迟、P95。

生产环境应换成 Prometheus/OpenTelemetry；这里保持零依赖，便于演示
`/api/metrics` 和压测前后对比。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict


class Metrics:
    def __init__(self, window: int = 1000) -> None:
        self._lock = threading.Lock()
        self._requests = 0
        self._errors = 0
        self._durations: Deque[float] = deque(maxlen=window)

    def record(self, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self._requests += 1
            if status_code >= 500:
                self._errors += 1
            self._durations.append(float(duration_ms))

    def summary(self) -> Dict[str, float]:
        with self._lock:
            requests = self._requests
            errors = self._errors
            durations = sorted(self._durations)
        if not durations:
            return {
                "requests": requests,
                "errors": errors,
                "error_rate": 0.0,
                "avg_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
            }
        index95 = min(len(durations) - 1, int(len(durations) * 0.95))
        index99 = min(len(durations) - 1, int(len(durations) * 0.99))
        return {
            "requests": requests,
            "errors": errors,
            "error_rate": round(errors / requests, 4) if requests else 0.0,
            "avg_ms": round(sum(durations) / len(durations), 1),
            "p50_ms": round(durations[len(durations) // 2], 1),
            "p95_ms": round(durations[index95], 1),
            "p99_ms": round(durations[index99], 1),
        }
