from shopagent.emotion import EmotionDetector
from shopagent.guardrails import contains_defensive_language


def test_list_categories(toolkit, ctx):
    result = toolkit.execute("list_categories", {}, ctx("user_004"))
    assert result["ok"] is True
    departments = [item["department"] for item in result["data"]["departments"]]
    assert "鞋" in departments
    assert "食品饮料" in departments
    assert "母婴" in departments


def test_search_by_department_and_audience(toolkit, ctx):
    result = toolkit.execute(
        "search_products",
        {"department": "鞋", "audience": "老人", "max_price": 300},
        ctx("user_004"),
    )
    assert result["ok"] is True
    names = [item["name"] for item in result["data"]["products"]]
    assert "老人防滑健步鞋" in names

    snacks = toolkit.execute(
        "search_products",
        {"department": "食品饮料", "audience": "儿童", "keyword": "零食"},
        ctx("user_005"),
    )
    assert snacks["ok"] is True
    assert any("奶酪" in item["name"] for item in snacks["data"]["products"])


def test_search_size_filter(toolkit, ctx):
    result = toolkit.execute(
        "search_products",
        {"department": "服饰", "audience": "男士", "size": "XL"},
        ctx("user_006"),
    )
    assert result["ok"] is True
    assert result["data"]["products"][0]["name"] == "男士纯棉衬衫"


def test_agent_handles_general_retail(agent):
    result = agent.chat(
        "给老人买一双防滑鞋，预算300以内",
        session_id="general-retail",
        user_id="user_004",
    )
    assert result.intent.intent == "pre_sales"
    assert any(trace.name == "search_products" for trace in result.tool_calls)
    assert "健步鞋" in result.reply


def test_agent_catalog(agent):
    result = agent.chat("你们卖什么", session_id="catalog", user_id="user_005")
    assert result.intent.intent == "catalog"
    assert any(trace.name == "list_categories" for trace in result.tool_calls)
    assert "食品饮料" in result.reply


def test_attitude_is_deescalated_not_auto_handoff():
    result = EmotionDetector().analyze("你啥态度")
    assert result.level == 1
    assert result.should_handoff is False


def test_defensive_language_guard():
    assert contains_defensive_language("行，那我直说。不演了。")
    assert contains_defensive_language("你爱买不买")
    assert not contains_defensive_language("抱歉，刚才我的表达让您不舒服了。")


def test_product_and_campaign_insights(toolkit, ctx):
    products = toolkit.execute(
        "product_insights",
        {"department": "服饰", "metric": "high_return", "limit": 3},
        ctx("user_006"),
    )
    assert products["ok"] is True
    assert products["data"]["items"]
    assert "return_rate" in products["data"]["items"][0]

    campaigns = toolkit.execute("campaign_insights", {}, ctx("user_001"))
    assert campaigns["ok"] is True
    assert campaigns["data"]["campaigns"]
    assert "roi" in campaigns["data"]["campaigns"][0]


def test_agent_analytics_intents(agent):
    products = agent.chat("哪个商品退货率高", session_id="analytics-products", user_id="user_006")
    assert products.intent.intent == "analytics"
    assert any(trace.name == "product_insights" for trace in products.tool_calls)
    assert "退货率" in products.reply

    campaigns = agent.chat("最近活动 ROI 怎么样", session_id="analytics-campaigns", user_id="user_001")
    assert campaigns.intent.intent == "analytics"
    assert any(trace.name == "campaign_insights" for trace in campaigns.tool_calls)
    assert "ROI" in campaigns.reply
