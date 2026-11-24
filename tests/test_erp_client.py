import httpx
from fastapi.testclient import TestClient

from shopagent.erp_client import HttpCommerceClient
from shopagent.mock_erp import app as erp_app


def test_erp_client_retries_5xx():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"detail": "busy"})
        return httpx.Response(200, json={"order_id": "DD2026001", "status": "已发货"})

    client = HttpCommerceClient(
        "http://erp.test",
        retries=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.get_order("DD2026001")
        assert result["status"] == "已发货"
        assert calls["count"] == 2
    finally:
        client.close()


def test_erp_client_sends_idempotency_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("Idempotency-Key")
        return httpx.Response(200, json={"return_id": "R123", "status": "pending_review"})

    client = HttpCommerceClient(
        "http://erp.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.create_return("DD2026009", "过敏", True, 1, idempotency_key="return-test-1")
        assert result["return_id"] == "R123"
        assert seen["key"] == "return-test-1"
    finally:
        client.close()


def test_mock_erp_order_and_logistics():
    client = TestClient(erp_app)
    order = client.get("/erp/orders/DD2026001")
    assert order.status_code == 200
    assert order.json()["tracking_no"] == "SF123456789"

    logistics = client.get("/erp/orders/DD2026001/logistics")
    assert logistics.status_code == 200
    assert logistics.json()["latest"]["status"] == "派送中"


def test_mock_erp_return_idempotency():
    client = TestClient(erp_app)
    headers = {"Idempotency-Key": "test-return-001"}
    payload = {"order_id": "DD2026009", "reason": "过敏", "opened": True, "quantity": 1}
    first = client.post("/erp/returns", json=payload, headers=headers)
    second = client.post("/erp/returns", json=payload, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["return_id"] == second.json()["return_id"]
