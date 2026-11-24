def test_search_products_filters_stock_and_budget(toolkit, ctx):
    result = toolkit.execute(
        "search_products",
        {"skin_type": "油皮", "concerns": ["控油"], "max_price": 300, "limit": 3},
        ctx("search_user"),
    )
    assert result["ok"] is True
    names = [item["name"] for item in result["data"]["products"]]
    assert "清润控油面霜" in names
    assert all(item["price"] <= 300 for item in result["data"]["products"])


def test_product_detail_and_stock(toolkit, ctx):
    detail = toolkit.execute("get_product_detail", {"product_name": "清润控油面霜"}, ctx())
    assert detail["ok"] is True
    assert "烟酰胺" in " ".join(detail["data"]["ingredients"])
    stock = toolkit.execute("check_stock", {"product_name": "清润控油面霜", "quantity": 2}, ctx())
    assert stock["ok"] is True
    assert stock["data"]["enough"] is True


def test_compare_products(toolkit, ctx):
    result = toolkit.execute(
        "compare_products",
        {"product_names": ["清润控油面霜", "修护保湿面霜"]},
        ctx(),
    )
    assert result["ok"] is True
    assert len(result["data"]["products"]) == 2


def test_order_privacy(toolkit, ctx):
    own = toolkit.execute("query_order", {"order_id": "DD2026001"}, ctx("user_001"))
    assert own["ok"] is True
    assert own["data"]["tracking_no"] == "SF123456789"
    other = toolkit.execute("query_order", {"order_id": "DD2026001"}, ctx("user_002"))
    assert other["ok"] is False
    assert other["error_code"] == "ORDER_NOT_FOUND"


def test_logistics(toolkit, ctx):
    result = toolkit.execute("query_logistics", {"order_id": "DD2026001"}, ctx("user_001"))
    assert result["ok"] is True
    assert result["data"]["tracking_no"] == "SF123456789"
    assert result["data"]["latest"]["status"] == "派送中"


def test_return_quality_case_allows_opened(toolkit, ctx):
    result = toolkit.execute(
        "create_return_request",
        {"order_id": "DD2026009", "reason": "使用后过敏/不适", "opened": True},
        ctx("user_001"),
    )
    assert result["ok"] is True
    assert result["data"]["return_id"].startswith("R")
    assert result["data"]["quality_case"] is True


def test_return_window_and_status_rules(toolkit, ctx):
    expired = toolkit.execute(
        "create_return_request",
        {"order_id": "DD2026005", "reason": "不喜欢/买错", "opened": False},
        ctx("user_001"),
    )
    assert expired["ok"] is False
    assert expired["error_code"] == "RETURN_WINDOW_EXPIRED"

    in_transit = toolkit.execute(
        "create_return_request",
        {"order_id": "DD2026001", "reason": "不喜欢/买错"},
        ctx("user_001"),
    )
    assert in_transit["ok"] is False
    assert in_transit["error_code"] == "ORDER_IN_TRANSIT"

    pending = toolkit.execute(
        "create_return_request",
        {"order_id": "DD2026002", "reason": "不喜欢/买错"},
        ctx("user_001"),
    )
    assert pending["ok"] is False
    assert pending["error_code"] == "ORDER_NOT_SHIPPED"


def test_coupon_cap_and_duplicate(toolkit, ctx):
    first = toolkit.execute(
        "issue_coupon",
        {"amount": 100, "reason": "价格异议"},
        ctx("coupon_user"),
    )
    assert first["ok"] is True
    assert first["data"]["amount"] == 20
    assert first["data"]["adjusted"] is True

    second = toolkit.execute(
        "issue_coupon",
        {"amount": 20, "reason": "再次索要"},
        ctx("coupon_user"),
    )
    assert second["ok"] is False
    assert second["error_code"] == "COUPON_LIMIT_REACHED"


def test_faq_search(toolkit, ctx):
    result = toolkit.execute("search_faq", {"query": "是正品吗"}, ctx())
    assert result["ok"] is True
    assert result["data"]["faq_id"] == "FAQ006"


def test_cart_flow(toolkit, ctx):
    added = toolkit.execute(
        "add_to_cart",
        {"product_name": "清润控油面霜", "quantity": 2},
        ctx("cart_user"),
    )
    assert added["ok"] is True
    assert added["data"]["count"] == 1
    assert added["data"]["total"] == 598
    viewed = toolkit.execute("view_cart", {}, ctx("cart_user"))
    assert viewed["data"]["items"][0]["quantity"] == 2


def test_handoff_is_idempotent(toolkit, ctx):
    first = toolkit.execute(
        "request_human_handoff",
        {"reason": "复杂售后", "priority": "high"},
        ctx("handoff_user"),
    )
    assert first["ok"] is True
    second = toolkit.execute(
        "request_human_handoff",
        {"reason": "再次要求", "priority": "urgent"},
        ctx("handoff_user"),
    )
    assert second["ok"] is True
    assert second["data"]["ticket_id"] == first["data"]["ticket_id"]


def test_update_profile(toolkit, ctx):
    result = toolkit.execute(
        "update_user_profile",
        {"skin_type": "敏感肌", "concerns": ["修护"], "budget": 260},
        ctx("profile_user"),
    )
    assert result["ok"] is True
    profile = toolkit.get_profile("profile_user")
    assert profile["skin_type"] == "敏感肌"
    assert profile["budget"] == 260
