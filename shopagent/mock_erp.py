"""Mock ERP/OMS 服务：用于演示商品、订单、物流、售后、优惠券的 HTTP 对接。

启动：python run_erp.py --port 8100
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
API_KEY = os.environ.get("ERP_API_KEY", "").strip()

PRODUCTS = {item["id"]: item for item in json.loads((DATA / "products.json").read_text(encoding="utf-8"))}
ORDERS = {item["order_id"]: item for item in json.loads((DATA / "orders.json").read_text(encoding="utf-8"))}
RETURNS: Dict[str, Dict[str, Any]] = {}
IDEMPOTENCY: Dict[str, Dict[str, Any]] = {}

app = FastAPI(title="Mock ERP/OMS", version="1.0.0")


def auth(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid ERP API key")


class ReturnRequest(BaseModel):
    order_id: str
    reason: str = "用户申请退货"
    opened: bool = False
    quantity: int = Field(default=1, ge=1, le=20)


class CouponRequest(BaseModel):
    user_id: str
    amount: int = Field(default=20, ge=1, le=20)
    reason: str = "retention"


@app.get("/erp/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "mock-erp", "products": len(PRODUCTS), "orders": len(ORDERS)}


@app.get("/erp/products/{product_id}")
def get_product(product_id: str, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> Dict[str, Any]:
    auth(x_api_key)
    product = PRODUCTS.get(product_id.upper())
    if not product:
        raise HTTPException(status_code=404, detail="product not found")
    return product


@app.get("/erp/orders/{order_id}")
def get_order(order_id: str, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> Dict[str, Any]:
    auth(x_api_key)
    order = ORDERS.get(order_id.upper())
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.get("/erp/orders/{order_id}/logistics")
def get_logistics(order_id: str, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> Dict[str, Any]:
    auth(x_api_key)
    order = ORDERS.get(order_id.upper())
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    timeline = order.get("timeline", [])
    return {
        "order_id": order["order_id"],
        "status": order.get("status"),
        "carrier": order.get("carrier"),
        "tracking_no": order.get("tracking_no"),
        "latest": timeline[-1] if timeline else {},
        "timeline": timeline[-5:],
        "estimated_delivery": order.get("estimated_delivery"),
    }


@app.post("/erp/returns")
def create_return(
    payload: ReturnRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    auth(x_api_key)
    if idempotency_key and idempotency_key in IDEMPOTENCY:
        return IDEMPOTENCY[idempotency_key]
    order = ORDERS.get(payload.order_id.upper())
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    return_id = "R" + secrets.token_hex(5).upper()
    record = {
        "return_id": return_id,
        "order_id": order["order_id"],
        "status": "pending_review",
        "refund_amount": float(order.get("paid", 0)),
        "reason": payload.reason,
        "opened": payload.opened,
        "quantity": payload.quantity,
        "idempotency_key": idempotency_key,
    }
    RETURNS[return_id] = record
    if idempotency_key:
        IDEMPOTENCY[idempotency_key] = record
    return record


@app.post("/erp/coupons")
def issue_coupon(
    payload: CouponRequest,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    auth(x_api_key)
    amount = min(20, max(1, payload.amount))
    return {
        "coupon_id": "C" + secrets.token_hex(4).upper(),
        "user_id": payload.user_id,
        "amount": amount,
        "status": "active",
        "reason": payload.reason,
    }
