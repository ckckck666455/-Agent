"""Locust 压测：先离线跑，避免压测打爆 DeepSeek 账单。

启动：
  pip install locust
  locust -f loadtest/locustfile.py --host http://127.0.0.1:8000
无 UI：
  locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 1m --host http://127.0.0.1:8000
"""
from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, task


MESSAGES = [
    "你们卖什么",
    "给老人买一双防滑鞋，预算300以内",
    "给5岁孩子买点零食，要安全一点",
    "给男士买一件通勤纯棉衬衫，XL",
    "我是油皮，想买300以内的面霜",
    "帮我查订单 DD2026001 到哪了",
    "哪个商品退货率高",
    "最近活动 ROI 怎么样",
]


class AgentUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.session_id = "load-" + uuid.uuid4().hex[:12]
        self.user_id = random.choice(["user_001", "user_004", "user_005", "user_006"])

    @task(8)
    def chat(self) -> None:
        message = random.choice(MESSAGES)
        with self.client.post(
            "/api/chat",
            json={"message": message, "session_id": self.session_id, "user_id": self.user_id},
            name="/api/chat",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure("HTTP %s" % response.status_code)
                return
            data = response.json()
            if not data.get("reply"):
                response.failure("empty reply")

    @task(1)
    def health(self) -> None:
        self.client.get("/api/health", name="/api/health")
