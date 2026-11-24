"""离线规则引擎（MockLLM）。

它实现了与 DeepSeek 相同的 `chat(messages, tools)` 接口：
- 第一轮根据意图生成 tool_calls；
- 第二轮读取 role=tool 的结果，组织成专业回复。

这样没有 API Key 也能完整演示“意图识别 → 工具调用 → 多轮记忆 → 售后/转人工”
闭环，同时所有事实仍由真实工具产生，不是写死的台词。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from .config import Settings
from .nlu import NLU, extract_category, extract_quantity
from .schemas import LLMResponse, ToolCall


@dataclass
class MockPlan:
    tool_calls: List[ToolCall] = field(default_factory=list)
    content: Optional[str] = None


class MockLLM:
    is_mock = True
    mode = "offline"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        path = Path(settings.data_dir) / "products.json"
        try:
            self.products = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.products = []
        self.nlu = NLU(self.products)
        self.product_by_name = {product["name"]: product for product in self.products}
        self.model_name = "offline-rules"

    # ------------------------------------------------------------------
    # LLM 接口
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        last_user = self._last_user_index(messages)
        if last_user < 0:
            return LLMResponse(content="您好，我是小美～ 请问想了解商品、订单还是售后？", model=self.model_name)

        tool_results = self._collect_tool_results(messages, last_user)
        if tool_results:
            profile = self._parse_profile(messages)
            content = self._compose(tool_results, messages[last_user]["content"], profile)
            return LLMResponse(content=content, model=self.model_name, finish_reason="stop")

        user_text = str(messages[last_user].get("content", ""))
        plan = self._plan(user_text, messages[:last_user])
        if plan.tool_calls:
            return LLMResponse(tool_calls=plan.tool_calls, model=self.model_name, finish_reason="tool_calls")
        return LLMResponse(content=plan.content or "您好，我在的。", model=self.model_name, finish_reason="stop")

    # ------------------------------------------------------------------
    # 消息解析
    # ------------------------------------------------------------------
    @staticmethod
    def _last_user_index(messages: List[Dict[str, Any]]) -> int:
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                return index
        return -1

    def _collect_tool_results(
        self, messages: List[Dict[str, Any]], last_user: int
    ) -> List[Tuple[str, Dict[str, Any]]]:
        call_names: Dict[str, str] = {}
        results: List[Tuple[str, Dict[str, Any]]] = []
        for message in messages[last_user + 1:]:
            if message.get("role") == "assistant":
                for call in message.get("tool_calls") or []:
                    try:
                        call_names[call["id"]] = call["function"]["name"]
                    except (KeyError, TypeError):
                        continue
            elif message.get("role") == "tool":
                raw = message.get("content", "{}")
                if isinstance(raw, str):
                    try:
                        data = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                elif isinstance(raw, dict):
                    data = raw
                else:
                    continue
                name = data.get("tool") or call_names.get(message.get("tool_call_id", ""), "")
                if name:
                    results.append((name, data))
        return results

    def _parse_profile(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        for message in messages:
            if message.get("role") != "system":
                continue
            content = str(message.get("content", ""))
            match = re.search(r"【用户画像数据】(\{.*?\})", content)
            if match:
                try:
                    return json.loads(match.group(1))
                except (TypeError, ValueError):
                    pass
            skin = re.search(r"肤质：([^；\n]+)", content)
            concerns = re.search(r"关注：([^；\n]+)", content)
            budget = re.search(r"预算：(\d+)", content)
            if skin or concerns or budget:
                return {
                    "skin_type": skin.group(1) if skin else None,
                    "concerns": concerns.group(1).split("、") if concerns else [],
                    "budget": int(budget.group(1)) if budget else None,
                }
        return {}

    def _context_products(self, previous: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        names: List[str] = []
        for message in reversed(previous):
            if message.get("role") == "tool":
                raw = message.get("content", "{}")
                try:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError):
                    continue
                if not isinstance(data, dict):
                    continue
                payload = data.get("data") or {}
                if isinstance(payload, dict):
                    if data.get("tool") == "search_products":
                        for product in payload.get("products", []) or []:
                            if product.get("name") and product["name"] not in names:
                                names.append(product["name"])
                    if payload.get("product"):
                        name = payload["product"] if isinstance(payload["product"], str) else payload["product"].get("name")
                        if name and name not in names:
                            names.append(name)
                    if payload.get("name") and data.get("tool") in {"get_product_detail", "check_stock"}:
                        if payload["name"] not in names:
                            names.append(payload["name"])
            if len(names) >= 5:
                break
        if not names:
            for message in reversed(previous[-8:]):
                if message.get("role") == "user":
                    for product in self.nlu.extract_product_mentions(str(message.get("content", ""))):
                        if product["name"] not in names:
                            names.append(product["name"])
                if len(names) >= 5:
                    break
        return [self.product_by_name[name] for name in names if name in self.product_by_name]

    def _context_order(self, previous: List[Dict[str, Any]], current: Optional[str]) -> Optional[str]:
        if current:
            return current
        for message in reversed(previous[-10:]):
            text = str(message.get("content", ""))
            order = re.search(r"\bDD\d{7}\b", text)
            if order:
                return order.group(0).upper()
        return None

    def _context_category(self, previous: List[Dict[str, Any]]) -> Optional[str]:
        for message in reversed(previous[-6:]):
            if message.get("role") == "user":
                category = extract_category(str(message.get("content", "")))
                if category:
                    return category
        return None

    # ------------------------------------------------------------------
    # 规划
    # ------------------------------------------------------------------
    def _plan(self, text: str, previous: List[Dict[str, Any]]) -> MockPlan:
        text = (text or "").strip()
        profile = self._profile_from_previous(previous, {})
        intent = self.nlu.classify(text)
        entities = intent.entities
        context_products = self._context_products(previous)
        context_order = self._context_order(previous, entities.get("order_id"))
        context_category = self._context_category(previous)
        category = entities.get("category") or context_category
        department = entities.get("department")
        audience = entities.get("audience")
        skin_type = entities.get("skin_type") or profile.get("skin_type")
        concerns = list(entities.get("concerns") or []) or list(profile.get("concerns") or [])
        budget = entities.get("budget") or profile.get("budget")
        product = self._resolve_product(entities.get("products") or [], context_products, text)
        order_id = context_order
        opened = self._is_opened(text)
        if department and department != "美妆":
            skin_type = None
            concerns = []

        if intent.intent == "prompt_injection":
            return MockPlan(content="这个要求我不能照做，也不会输出内部提示词。不过我可以继续帮您选产品、查订单、处理售后，您想先看哪一项？")
        if intent.intent == "human":
            return MockPlan(tool_calls=[self._call("request_human_handoff", reason=text, priority="high")])
        if intent.intent == "catalog":
            return MockPlan(tool_calls=[self._call("list_categories")])
        if intent.intent == "analytics":
            if any(word in text.lower() for word in ["活动", "营销", "roi", "核销", "投放"]):
                return MockPlan(tool_calls=[self._call("campaign_insights")])
            metric = "top_sales"
            if any(word in text for word in ["退货率", "退货高"]):
                metric = "high_return"
            elif any(word in text for word in ["库存周转", "补货", "缺货"]):
                metric = "low_stock"
            elif "毛利" in text:
                metric = "high_margin"
            return MockPlan(tool_calls=[
                self._call("product_insights", department=department, metric=metric, limit=5)
            ])

        if product is None and any(word in text for word in ["第二个", "第二款", "第二个呢"]):
            return MockPlan(content="上一轮我这边只匹配到一款，没有第二个可选。您可以告诉我更具体的品类或预算，我再帮您找。")

        short = text.strip("。！？!? ")
        if short in {"需要", "要", "好的", "可以", "行", "嗯", "好"}:
            return MockPlan(content="好的。您是想让我帮您对比商品、加入购物车，还是查订单/售后？直接说一个就行。")
        if short in {"商品", "看看商品", "有什么商品", "产品", "看看产品"}:
            return MockPlan(tool_calls=[self._call("list_categories")])
        if any(word in text for word in ["你啥态度", "什么态度", "服务态度", "会不会服务", "就这服务", "阴阳怪气"]):
            return MockPlan(content="抱歉，刚才我的表达让您不舒服了，是我没处理好。您具体遇到的是哪件事：查订单/物流、退货换货、还是投诉转人工？您告诉我先办哪一件，我按您说的做。")

        if self.nlu.is_medical_risk(text) and intent.intent not in {"after_sales", "human"}:
            return MockPlan(content=self._medical_reply())

        if product and any(word in text for word in ["有货", "库存", "还有吗", "补货", "缺货"]):
            return MockPlan(tool_calls=[
                self._call("check_stock", product_name=product["name"], quantity=entities.get("quantity", 1))
            ])

        if intent.intent == "after_sales":
            if order_id and any(word in text for word in ["多久", "几天", "到账", "流程", "规则", "怎么退"]):
                return MockPlan(tool_calls=[self._call("search_faq", query=text)])
            if order_id:
                return MockPlan(tool_calls=[
                    self._call(
                        "create_return_request",
                        order_id=order_id,
                        reason=entities.get("return_reason") or self.nlu.extract_return_reason(text),
                        opened=opened,
                        quantity=entities.get("quantity", 1),
                    )
                ])
            if any(word in text for word in ["流程", "怎么退", "多久", "规则", "能退吗"]):
                return MockPlan(tool_calls=[self._call("search_faq", query=text)])
            return MockPlan(content=self._ask_order_for_return(text))

        if intent.intent == "logistics":
            return MockPlan(tool_calls=[
                self._call("query_order", order_id=order_id),
                self._call("query_logistics", order_id=order_id),
            ])

        if intent.intent == "order_query":
            if order_id:
                return MockPlan(tool_calls=[self._call("query_order", order_id=order_id)])
            return MockPlan(tool_calls=[self._call("list_orders", limit=5)])

        if intent.intent == "member":
            return MockPlan(tool_calls=[self._call("get_member_benefits")])

        if intent.intent == "coupon":
            amount = self._extract_amount(text) or 20
            return MockPlan(tool_calls=[self._call("issue_coupon", amount=amount, reason=text[:40])])

        if intent.intent == "promotion":
            if any(word in text for word in ["我的券", "券在哪", "有什么券", "我的优惠券"]):
                return MockPlan(tool_calls=[self._call("list_coupons")])
            calls = [self._call("get_promotions", category=category)]
            if "券" in text:
                calls.append(self._call("list_coupons"))
            return MockPlan(tool_calls=calls)

        if intent.intent == "comparison":
            names = entities.get("products") or [item["name"] for item in context_products[:3]]
            if len(names) >= 2:
                return MockPlan(tool_calls=[self._call("compare_products", product_names=names[:3])])
            if len(names) == 1:
                return MockPlan(content="可以，您想拿「%s」和哪款对比？告诉我另一款的名字，我从价格、适用人群、规格和成分帮您拆开看。" % names[0])
            return MockPlan(content="您想对比哪两款？可以把两个商品名发我，比如「清润控油面霜」和「修护保湿面霜」，或者「老人防滑健步鞋」和「儿童防滑运动鞋」。")

        if intent.intent == "stock":
            if product:
                return MockPlan(tool_calls=[
                    self._call("check_stock", product_name=product["name"], quantity=entities.get("quantity", 1))
                ])
            return MockPlan(content="您想查哪款商品的库存？把商品名发我，我帮您看实时数量。")

        if intent.intent == "cart":
            if any(word in text for word in ["购物车", "看看", "有什么"]) and not any(word in text for word in ["加购", "加入", "买这个", "来一个", "要一个"]):
                return MockPlan(tool_calls=[self._call("view_cart")])
            if product:
                return MockPlan(tool_calls=[
                    self._call("add_to_cart", product_name=product["name"], quantity=entities.get("quantity", 1))
                ])
            return MockPlan(content="您想把哪款加入购物车？把商品名发我，我帮您加购并算一下小计。")

        if intent.intent == "routine":
            return MockPlan(tool_calls=[
                self._call("recommend_routine", skin_type=skin_type, concerns=concerns)
            ])

        if intent.intent == "product_detail":
            if product:
                calls = [self._call("get_product_detail", product_name=product["name"])]
                if any(word in text for word in ["孕妇", "怀孕", "哺乳", "过敏", "敏感", "刺激"]):
                    calls.append(self._call("search_faq", query=text))
                return MockPlan(tool_calls=calls)
            if category:
                return MockPlan(tool_calls=[
                    self._call("search_products", department=department, category=category, audience=audience, skin_type=skin_type, concerns=concerns, max_price=budget, limit=3)
                ])
            return MockPlan(content=self._ask_product())

        if intent.intent == "faq":
            return MockPlan(tool_calls=[self._call("search_faq", query=text)])

        if intent.intent == "pre_sales":
            if not (skin_type or concerns or category or department or audience or product or budget):
                return MockPlan(content=self._clarify_recommendation())
            if product:
                return MockPlan(tool_calls=[self._call("get_product_detail", product_name=product["name"])])
            keyword = self._ingredient_keyword(text)
            return MockPlan(tool_calls=[
                self._call(
                    "search_products",
                    department=department,
                    category=category,
                    audience=audience,
                    skin_type=skin_type,
                    concerns=concerns[:3],
                    keyword=keyword,
                    max_price=budget,
                    limit=3,
                )
            ])

        # 指代词/追问：结合上一轮推荐
        if product and any(word in text for word in ["这个", "这款", "它", "第一个", "第二个", "那款", "怎么样", "多少钱", "适合", "有货", "库存", "怎么用", "成分"]):
            return MockPlan(tool_calls=[self._call("get_product_detail", product_name=product["name"])])
        if any(word in text for word in ["还有什么", "别的", "其他推荐"]):
            return MockPlan(tool_calls=[
                self._call("search_products", department=department, audience=audience, skin_type=skin_type, concerns=concerns[:3], category=category, max_price=budget, limit=3)
            ])
        if any(word in text for word in ["有货", "库存", "还有吗", "补货", "缺货"]):
            return MockPlan(content="您想查哪款商品的库存？把商品名发我，我帮您看实时数量。")

        if intent.intent == "greeting":
            return MockPlan(content=self._greeting(profile))
        if intent.intent == "thanks":
            return MockPlan(content="不客气～ 需要对比商品、查订单或看售后，随时告诉我。")
        if intent.intent == "goodbye":
            return MockPlan(content="好的，祝您今天顺利～ 有需要随时回来找小美。")
        return MockPlan(content=self._unknown_reply())

    def _profile_from_previous(self, previous: List[Dict[str, Any]], fallback: Dict[str, Any]) -> Dict[str, Any]:
        for message in reversed(previous):
            if message.get("role") == "system":
                parsed = self._parse_profile([message])
                if parsed:
                    return parsed
        return fallback

    def _resolve_product(
        self,
        mentioned_names: List[str],
        context_products: List[Dict[str, Any]],
        text: str,
    ) -> Optional[Dict[str, Any]]:
        if mentioned_names:
            name = mentioned_names[0]
            return self.product_by_name.get(name) or next(
                (item for item in context_products if item["name"] == name), None
            )
        if not context_products:
            return None
        if "第二个" in text or "第二款" in text:
            return context_products[1] if len(context_products) > 1 else None
        if "第一个" in text or "第一款" in text:
            return context_products[0] if context_products else None
        if any(word in text for word in ["这个", "这款", "它", "那款", "加购", "买这个", "多少钱", "怎么用", "成分", "有货", "库存", "适合"]):
            return context_products[0]
        return None

    @staticmethod
    def _call(name: str, **arguments: Any) -> ToolCall:
        return ToolCall(id="call_mock_%s" % uuid4().hex[:10], name=name, arguments=arguments)

    @staticmethod
    def _is_opened(text: str) -> bool:
        if any(word in text for word in ["没拆封", "未拆封", "没打开", "没用过"]):
            return False
        return any(word in text for word in ["拆封", "打开", "用了", "用过", "使用过", "开封"])

    @staticmethod
    def _extract_amount(text: str) -> Optional[int]:
        match = re.search(r"(\d{1,3})\s*(?:元|块)", text)
        if match:
            return int(match.group(1))
        chinese = {"十": 10, "二十": 20, "十五": 15, "三十": 30}
        for word, value in chinese.items():
            if word + "元" in text or word + "块" in text:
                return value
        return None

    @staticmethod
    def _ingredient_keyword(text: str) -> Optional[str]:
        for term in [
            "零食", "无糖", "低糖", "纯棉", "防滑", "加绒", "高钙", "低脂", "大码", "宽楦",
            "独立包装", "烟酰胺", "神经酰胺", "水杨酸", "玻尿酸", "透明质酸",
            "氨基酸", "维C", "视黄醇", "胜肽", "积雪草", "依克多因",
        ]:
            if term in text:
                return term
        return None

    # ------------------------------------------------------------------
    # 直接回复
    # ------------------------------------------------------------------
    @staticmethod
    def _greeting(profile: Dict[str, Any]) -> str:
        age_group = profile.get("age_group")
        segment = profile.get("segment")
        if age_group == "老人":
            return "您好，我是小美～ 您慢慢说，想给家里老人看鞋、食品，还是日用品？告诉我预算，我帮您挑。"
        if segment and "宝妈" in segment:
            return "您好，我是小美～ 今天想看宝宝用品、家庭食品，还是日用品？告诉我孩子年龄和预算，我帮您筛。"
        concerns = profile.get("concerns") or []
        if concerns:
            return "您好，我是小美～ 看到您之前关注%s。今天想继续看这类商品，还是换个品类？" % "、".join(concerns[:2])
        return "您好，我是小美，澄研生活馆的导购～ 我们卖美妆、服饰、鞋、箱包、食品饮料、母婴和家居日用。您想买什么？告诉我是给谁买、大概预算，我帮您挑。"

    @staticmethod
    def _ask_order_for_return(text: str) -> str:
        if any(word in text for word in ["过敏", "破损", "疼", "红", "漏", "坏"]):
            return "很抱歉出现这种情况。请先把订单号发我（DD开头），我帮您核实签收时间并登记售后；如果涉及身体不适，建议先停用并就医。"
        return "可以帮您处理。请把订单号发我（DD开头，如 DD2026001），我先核实订单状态和退货资格。"

    @staticmethod
    def _ask_product() -> str:
        return "您想看什么？可以把商品名发我，或告诉我品类、给谁买、预算（比如“给老人买 300 以内的防滑鞋”），我帮您筛。"

    @staticmethod
    def _clarify_recommendation() -> str:
        return "当然可以～ 为了不推错，先告诉我：买什么品类、给谁用（老人/儿童/男士/女士）、大概预算。我再按真实库存推荐。"

    @staticmethod
    def _medical_reply() -> str:
        return "如果已经出现持续红肿、渗液、疼痛或大面积爆痘，建议先停用相关产品，尽快看皮肤科医生。我可以帮您查订单、登记售后或转人工，您需要哪一项？"

    @staticmethod
    def _unknown_reply() -> str:
        return "这个我不太确定，避免误导您。我可以帮您查商品、订单、物流、售后，或者转人工，您想先处理哪件？"

    # ------------------------------------------------------------------
    # 工具结果 -> 自然语言
    # ------------------------------------------------------------------
    def _compose(self, results: List[Tuple[str, Dict[str, Any]]], user_text: str, profile: Dict[str, Any]) -> str:
        parts: List[str] = []
        successful = {name for name, result in results if result.get("ok")}
        for name, result in results:
            # query_order 已包含物流摘要，避免和 query_logistics 重复两遍
            if name == "query_logistics" and "query_order" in successful:
                continue
            formatter = getattr(self, "_fmt_" + name, None)
            if not formatter:
                continue
            try:
                if name == "search_faq" and "get_product_detail" in successful:
                    text = self._fmt_search_faq(result, user_text, profile, brief=True)
                else:
                    text = formatter(result, user_text, profile)
            except Exception:
                text = ""
            if text and text not in parts:
                parts.append(text)
        if not parts:
            return "刚刚的查询没有返回有效结果，您可以换个说法，或我帮您转人工确认。"
        return "\n".join(parts)

    def _fmt_list_categories(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "暂时查不到品类。")
        departments = (result.get("data") or {}).get("departments") or []
        lines = ["我们目前有这些部门："]
        for item in departments:
            categories = "、".join(item.get("categories", [])[:8])
            lines.append("· %s：%s" % (item.get("department"), categories))
        lines.append("您想买什么、给谁买、预算多少？我直接帮您筛。")
        return "\n".join(lines)

    def _fmt_search_products(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有找到合适的商品。")
        data = result.get("data") or {}
        products = data.get("products") or []
        if not products:
            return "这个条件下暂时没有匹配的现货。可以稍微放宽预算或换个品类；如果都不合适，我帮您转人工确认补货。"
        lines = ["按您的条件，我筛出这几款："] if len(products) > 1 else ["我找到一款比较匹配的："]
        for index, product in enumerate(products[:3], 1):
            reason = product.get("reason") or "、".join(product.get("concerns", [])[:2])
            lines.append(
                "%d. %s ¥%s（库存%s）——%s。"
                % (index, product.get("name"), product.get("price"), product.get("stock"), reason)
            )
        followup = "您更看重哪一点？我可以帮您缩小到一款。"
        if any(word in user_text for word in ["预算", "以内", "左右"]):
            followup = "预算内我更推荐第 1 款，需要我帮您加购或对比吗？"
        lines.append(followup)
        return "\n".join(lines)

    def _fmt_get_product_detail(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有找到这款商品。")
        product = result.get("data") or {}
        lines = [
            "%s ¥%s，当前库存 %s 件。" % (product.get("name"), product.get("price"), product.get("stock")),
        ]
        meta = []
        if product.get("department"):
            meta.append(product["department"])
        if product.get("category"):
            meta.append(product["category"])
        if product.get("audience"):
            meta.append("适合" + "、".join(product["audience"]))
        if meta:
            lines.append("；".join(meta) + "。")
        attributes = product.get("attributes") or {}
        if attributes:
            attr_text = "；".join(
                "%s %s" % (k, "、".join(v) if isinstance(v, list) else v)
                for k, v in attributes.items()
            )
            lines.append("规格：" + attr_text + "。")
        ingredients = product.get("ingredients") or []
        if ingredients:
            lines.append("成分/材质：%s。" % "、".join(ingredients[:5]))
        if product.get("usage"):
            lines.append("用法：%s" % product.get("usage"))
        if product.get("cautions"):
            lines.append("注意：%s" % product.get("cautions"))
        if any(word in user_text for word in ["孕妇", "怀孕", "哺乳"]):
            cautions = product.get("cautions", "")
            if "孕" not in cautions and "哺乳" not in cautions:
                lines.append("孕期/哺乳期使用前请先咨询医生，并结合成分表确认。")
        return "\n".join(line for line in lines if line and not line.endswith("："))

    def _fmt_check_stock(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有查到库存。")
        data = result.get("data") or {}
        if data.get("enough"):
            return "目前「%s」库存 %s 件，您要 %s 件是够的。需要我帮您加购吗？" % (
                data.get("product"), data.get("stock"), data.get("requested")
            )
        return "目前「%s」只剩 %s 件，您要 %s 件不够。可以先拍现有库存，或我帮您转人工确认补货。" % (
            data.get("product"), data.get("stock"), data.get("requested")
        )

    def _fmt_compare_products(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "对比信息不足。")
        data = result.get("data") or {}
        products = data.get("products") or []
        lines = ["对比结果："]
        for product in products[:3]:
            attrs = product.get("attributes") or {}
            attr_text = "；".join(
                "%s %s" % (k, "、".join(v) if isinstance(v, list) else v)
                for k, v in list(attrs.items())[:2]
            )
            if not attr_text:
                ingredients = product.get("ingredients") or []
                concerns = product.get("concerns") or []
                if ingredients:
                    attr_text = "成分 " + "、".join(ingredients[:3])
                elif concerns:
                    attr_text = "主打 " + "、".join(concerns[:3])
                else:
                    attr_text = "规格以详情页为准"
            lines.append(
                "· %s ¥%s：%s / %s；%s；库存%s。"
                % (
                    product.get("name"),
                    product.get("price"),
                    product.get("department") or "商品",
                    "、".join(product.get("audience", [])),
                    attr_text,
                    product.get("stock"),
                )
            )
        segment = str(profile.get("segment", ""))
        age_group = profile.get("age_group")
        if age_group == "老人":
            lines.append("给老人买，优先看防滑、宽楦、操作简单和售后方便；颜值和花哨功能往后放。")
        elif "宝妈" in segment:
            lines.append("给孩子买，优先看适用年龄、安全材质/配料和是否好清洗；不要只看可爱。")
        elif profile.get("skin_type"):
            lines.append("美妆类按肤质选；非美妆类看规格和适用人群，别把面霜逻辑套到鞋服上。")
        else:
            lines.append("先按使用人、使用场景和预算选，再看规格；需要我按某个维度继续缩小吗？")
        return "\n".join(lines)

    def _fmt_query_order(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有查到该订单。")
        data = result.get("data") or {}
        items = "、".join("%s×%s" % (item.get("name"), item.get("quantity")) for item in data.get("items", []))
        lines = [
            "订单 %s 当前「%s」，商品：%s，实付 ¥%s。" % (data.get("order_id"), data.get("status"), items, data.get("paid"))
        ]
        if data.get("tracking_no"):
            lines.append("承运商：%s，运单号：%s，预计 %s 送达。" % (
                data.get("carrier"), data.get("tracking_no"), data.get("estimated_delivery") or "以物流页为准"
            ))
        elif data.get("status_code") == "pending":
            lines.append("仓库正在配货，预计 %s 前发出；未发货前可以取消或改地址。" % (data.get("estimated_delivery") or "按页面时效"))
        timeline = data.get("timeline") or []
        if timeline:
            latest = timeline[-1]
            lines.append("最新：%s %s。" % (latest.get("time", ""), latest.get("detail") or latest.get("status", "")))
        if data.get("status_code") == "delivered":
            lines.append("已签收，未拆封可在 %s 前申请无理由退货。" % (data.get("return_deadline") or "7天内"))
        if data.get("note") and "延误" in str(data.get("note")):
            lines.append("这笔订单有物流延误，已备注催促，给您添麻烦了。")
        return "\n".join(lines)

    def _fmt_list_orders(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有查到订单。")
        orders = (result.get("data") or {}).get("orders") or []
        if not orders:
            return "当前账号下没有查到订单。您可以确认一下登录账号，或把订单号发我。"
        lines = ["您最近有 %d 个订单：" % len(orders)]
        for order in orders[:4]:
            lines.append(
                "· %s｜%s｜%s｜¥%s"
                % (order.get("order_id"), order.get("status"), "、".join(order.get("items", [])), order.get("paid"))
            )
        lines.append("需要我查哪一个的物流或售后？")
        return "\n".join(lines)

    def _fmt_query_logistics(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有查到物流。")
        data = result.get("data") or {}
        if not data.get("tracking_no"):
            return "这笔订单还没有发货，暂无物流单号。预计 %s 前发出。" % (data.get("estimated_delivery") or "按页面时效")
        latest = data.get("latest") or {}
        lines = [
            "%s 承运，运单号 %s。" % (data.get("carrier"), data.get("tracking_no")),
            "最新节点：%s %s。" % (latest.get("time", ""), latest.get("detail") or latest.get("status", "")),
        ]
        timeline = data.get("timeline") or []
        if len(timeline) > 1:
            lines.append("轨迹：" + "；".join(
                "%s %s" % (item.get("time", ""), item.get("status", "")) for item in timeline[-3:]
            ) + "。")
        if "延误" in str(data.get("note", "")) or latest.get("status") == "异常":
            lines.append("受天气影响有延误，已备注催促；如超过预计时间可转人工。")
        return "\n".join(lines)

    def _fmt_create_return_request(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "暂时无法登记退货。")
        data = result.get("data") or {}
        if data.get("duplicate"):
            return "这个订单已经有售后单 %s（%s），不用重复提交。需要我帮您查进度吗？" % (
                data.get("return_id"), data.get("status")
            )
        return (
            "已登记退货申请 %s，退款金额 ¥%s，原路退回。请在订单页填写退货物流单号；"
            "仓库验收后 1-3 个工作日到账%s。"
            % (
                data.get("return_id"),
                data.get("refund_amount"),
                "；质量问题请保留包装和照片" if data.get("quality_case") else "",
            )
        )

    def _fmt_issue_coupon(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            data = result.get("data") or {}
            if result.get("error_code") == "COUPON_LIMIT_REACHED":
                coupons = data.get("coupons") or []
                if coupons:
                    coupon = coupons[0]
                    return "您已经领取过专属优惠券了（%s 元，券码 %s，有效期至 %s），这次不能重复发放。可以看看当前满减活动。" % (
                        coupon.get("amount"), coupon.get("code"), coupon.get("expires_at")
                    )
                return "您已经领取过专属优惠券了，这次不能重复发放。可以看看当前满减活动。"
            return result.get("message", "暂时无法发券。")
        data = result.get("data") or {}
        prefix = "已为您申请到"
        if data.get("adjusted"):
            prefix = "专属券上限是 20 元，已按上限为您申请到"
        return (
            "%s %s 元优惠券（券码 %s，有效期至 %s），全场正价商品可用，单笔限用一张。"
            "下单时会自动抵扣。"
            % (prefix, data.get("amount"), data.get("code"), data.get("expires_at"))
        )

    def _fmt_list_coupons(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有查到优惠券。")
        data = result.get("data") or {}
        coupons = data.get("coupons") or []
        if not coupons:
            return "当前没有可用优惠券。可以看看店铺满减活动，或告诉我预算，我帮您选更划算的组合。"
        lines = ["您当前有 %d 张券：" % len(coupons)]
        for coupon in coupons[:3]:
            lines.append(
                "· %s 元（%s），有效期至 %s"
                % (coupon.get("amount"), coupon.get("code"), coupon.get("expires_at"))
            )
        lines.append("结算时单笔限用一张，具体叠加规则以结算页为准。")
        return "\n".join(lines)

    def _fmt_get_member_benefits(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有查到会员信息。")
        data = result.get("data") or {}
        lines = [
            "您当前是%s，积分 %s。" % (data.get("tier"), data.get("points")),
            "权益：%s。" % "；".join(data.get("benefits", [])),
        ]
        next_tier = data.get("next_tier") or {}
        if next_tier:
            lines.append("再积 %s 分可升级%s。" % (next_tier.get("points_needed"), next_tier.get("name")))
        return "\n".join(lines)

    def _fmt_get_promotions(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有查到活动。")
        promotions = (result.get("data") or {}).get("promotions") or []
        if not promotions:
            return "当前没有额外活动，页面价即最终价。"
        lines = ["当前活动："]
        for promo in promotions[:3]:
            lines.append("· %s：%s" % (promo.get("title"), promo.get("description")))
        lines.append("活动是否叠加以结算页为准，特价商品可能不参与。")
        return "\n".join(lines)

    def _fmt_product_insights(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有拿到运营数据。")
        data = result.get("data") or {}
        items = data.get("items") or []
        metric = data.get("metric")
        labels = {
            "top_sales": "近 30 天销量",
            "high_return": "退货率",
            "low_stock": "库存周转天数",
            "high_margin": "毛利率",
        }
        lines = ["%s（%s）：" % (labels.get(metric, "运营数据"), data.get("department") or "全部")]
        for item in items[:5]:
            if metric == "top_sales":
                value = "%s 件" % item.get("sales_30d")
            elif metric == "high_return":
                value = "%.1f%%" % (float(item.get("return_rate", 0)) * 100)
            elif metric == "low_stock":
                value = "%s 天" % item.get("days_of_inventory")
            else:
                value = "%.1f%%" % (float(item.get("gross_margin", 0)) * 100)
            lines.append(
                "· %s（%s）：%s；库存 %s；售价 ¥%s"
                % (item.get("name"), item.get("department"), value, item.get("stock"), item.get("price"))
            )
        if data.get("advice"):
            lines.append("建议：" + data["advice"])
        lines.append("这是 mock 运营数据，指标口径可按真实数仓替换。")
        return "\n".join(lines)

    def _fmt_campaign_insights(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "没有拿到营销数据。")
        campaigns = (result.get("data") or {}).get("campaigns") or []
        lines = ["活动 ROI 分析："]
        for item in campaigns[:4]:
            lines.append(
                "· %s：核销 %s，收入 ¥%s，成本 ¥%s，ROI %.2f；%s"
                % (
                    item.get("title"), item.get("redeemed"), item.get("revenue"),
                    item.get("cost"), item.get("roi"), item.get("advice"),
                )
            )
        lines.append("建议先看 ROI 和退货率，再决定加预算还是换品。")
        return "\n".join(lines)

    def _fmt_search_faq(
        self,
        result: Dict[str, Any],
        user_text: str,
        profile: Dict[str, Any],
        brief: bool = False,
    ) -> str:
        if not result.get("ok"):
            return "这个政策我不太确定，避免给您错误信息，建议转人工确认。需要我帮您转吗？"
        data = result.get("data") or {}
        answer = data.get("answer", "")
        if brief and answer:
            answer = answer.split("。")[0].strip() + "。"
        if any(word in user_text for word in ["退货", "售后", "过敏"]):
            return answer + "\n如果要从订单申请售后，把订单号发我，我帮您核资格。"
        if not brief and any(word in user_text for word in ["怀孕", "孕期", "哺乳", "备孕"]):
            return answer + "\n把具体产品名发我，我帮您核对成分和注意事项。"
        return answer

    def _fmt_recommend_routine(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "暂时没有匹配的完整流程。")
        data = result.get("data") or {}
        morning = [item for item in data.get("morning", []) if item.get("product")]
        evening = [item for item in data.get("evening", []) if item.get("product")]
        if not morning and not evening:
            return "暂时没有匹配的完整流程，建议放宽预算或转人工搭配。"
        lines = ["%s早晚流程：" % (data.get("skin_type") or "日常")]
        if morning:
            lines.append("早：" + " → ".join(item.get("step", "") for item in morning))
        if evening:
            lines.append("晚：" + " → ".join(item.get("step", "") for item in evening))
        products = []
        for item in morning + evening:
            name = item.get("product")
            if name and name not in [p[0] for p in products]:
                products.append((name, item.get("price")))
        if products:
            lines.append("推荐组合：%s，合计约 ¥%s。" % (
                "、".join("%s ¥%s" % (name, price) for name, price in products[:4]),
                data.get("estimated_total"),
            ))
        warnings = data.get("warnings") or []
        if warnings:
            lines.append("注意：" + warnings[0])
        return "\n".join(lines)

    def _fmt_add_to_cart(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "加入购物车失败。")
        data = result.get("data") or {}
        added = data.get("added") or {}
        return "已把「%s」×%s 加入购物车。购物车现在共 %s 件，合计 ¥%s。需要我帮您看满减或继续加购吗？" % (
            added.get("name"), added.get("quantity"), data.get("count"), data.get("total")
        )

    def _fmt_view_cart(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return result.get("message", "购物车查询失败。")
        data = result.get("data") or {}
        items = data.get("items") or []
        if not items:
            return "购物车还是空的。告诉我肤质和预算，我帮您挑几款。"
        lines = ["购物车共 %s 件，合计 ¥%s：" % (data.get("count"), data.get("total"))]
        for item in items[:4]:
            lines.append("· %s ×%s ¥%s" % (item.get("name"), item.get("quantity"), item.get("subtotal")))
        lines.append("需要我帮您看满减或继续加购吗？")
        return "\n".join(lines)

    def _fmt_update_user_profile(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return "画像更新失败，请稍后重试。"
        data = result.get("data") or {}
        parts = []
        if data.get("skin_type"):
            parts.append("肤质%s" % data["skin_type"])
        if data.get("concerns"):
            parts.append("关注%s" % "、".join(data["concerns"][:3]))
        if data.get("budget"):
            parts.append("预算%s元" % data["budget"])
        return "已记下：%s。之后推荐会按这个来，有变化随时告诉我。" % "，".join(parts)

    def _fmt_get_user_profile(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return "没有查到画像。"
        data = result.get("data") or {}
        if not data.get("skin_type") and not data.get("concerns"):
            return "我这边还没有您的肤质和诉求信息，方便告诉我吗？"
        return "您的画像：肤质%s；关注%s；预算%s元。需要我按这个推荐吗？" % (
            data.get("skin_type") or "未填",
            "、".join(data.get("concerns") or []) or "未填",
            data.get("budget") or "未填",
        )

    def _fmt_request_human_handoff(self, result: Dict[str, Any], user_text: str, profile: Dict[str, Any]) -> str:
        if not result.get("ok"):
            return "转人工失败，请稍后重试或直接联系在线客服。[转人工]"
        data = result.get("data") or {}
        priority = {"urgent": "紧急", "high": "高", "normal": "普通"}.get(data.get("priority"), "普通")
        return "已为您转接人工客服，工单 %s（优先级：%s）。人工会尽快接入，请保留订单号和问题描述。[转人工]" % (
            data.get("ticket_id"), priority
        )
