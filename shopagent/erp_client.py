"""ERP/OMS HTTP 客户端：超时、重试、幂等键与错误映射。

真实项目里把 `ERP_BASE_URL` 指向商品/订单/物流/售后系统即可；
没有配置时 Agent 继续使用本地 JSON，不影响离线演示。
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

import httpx


class ERPError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, code: str = "ERP_ERROR") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class HttpCommerceClient:
    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = 5.0,
        retries: int = 2,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.retries = max(0, retries)
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                response = self._client.request(method, path, json=json, headers=headers)
                if response.status_code >= 500:
                    raise ERPError(
                        "ERP 服务暂时不可用（HTTP %s）" % response.status_code,
                        status_code=response.status_code,
                        code="ERP_UPSTREAM_5XX",
                    )
                if response.status_code == 401:
                    raise ERPError("ERP 鉴权失败", status_code=401, code="ERP_UNAUTHORIZED")
                if response.status_code == 404:
                    raise ERPError("ERP 未找到资源", status_code=404, code="ERP_NOT_FOUND")
                if response.status_code >= 400:
                    raise ERPError(
                        "ERP 请求失败（HTTP %s）" % response.status_code,
                        status_code=response.status_code,
                        code="ERP_UPSTREAM_4XX",
                    )
                return response.json()
            except ERPError as exc:
                last_error = exc
                if exc.status_code in {400, 401, 403, 404} or attempt >= self.retries:
                    raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise ERPError("ERP 请求超时或网络异常", code="ERP_NETWORK") from exc
            time.sleep(0.05 * (2 ** attempt))
        raise ERPError(str(last_error or "ERP 请求失败"), code="ERP_UNKNOWN")

    def get_order(self, order_id: str) -> Dict[str, Any]:
        return self._request("GET", "/erp/orders/%s" % order_id)

    def get_logistics(self, order_id: str) -> Dict[str, Any]:
        return self._request("GET", "/erp/orders/%s/logistics" % order_id)

    def get_product(self, product_id: str) -> Dict[str, Any]:
        return self._request("GET", "/erp/products/%s" % product_id)

    def create_return(
        self,
        order_id: str,
        reason: str,
        opened: bool = False,
        quantity: int = 1,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/erp/returns",
            json={
                "order_id": order_id,
                "reason": reason,
                "opened": opened,
                "quantity": quantity,
            },
            idempotency_key=idempotency_key or ("return-%s-%s" % (order_id, uuid.uuid4().hex[:12])),
        )

    def issue_coupon(self, user_id: str, amount: int, reason: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/erp/coupons",
            json={"user_id": user_id, "amount": amount, "reason": reason},
            idempotency_key="coupon-%s-%s" % (user_id, uuid.uuid4().hex[:12]),
        )
