"""业务工具层：商品、订单、物流、售后、优惠券、会员、FAQ、购物车、转人工。

原则：
1. 工具返回结构化 JSON，模型只负责组织语言；
2. 用户身份由服务端上下文注入，工具 schema 不暴露 user_id，避免越权；
3. 所有业务规则（券上限、退货窗口、订单归属）在代码层硬约束。
"""
from __future__ import annotations

import difflib
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .erp_client import ERPError, HttpCommerceClient
from .guardrails import clean_arguments, normalize_bool, normalize_int
from .knowledge import KnowledgeBase
from .storage import Store, now_iso


def _norm(value: str) -> str:
    return "".join(str(value or "").lower().split())


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").replace("、", ",").split(",") if item.strip()]
    return [str(value)]


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _ok(data: Any = None, message: str = "", **extra: Any) -> Dict[str, Any]:
    result = {"ok": True, "data": data if data is not None else {}, "message": message}
    result.update(extra)
    return result


def _err(code: str, message: str, data: Any = None, **extra: Any) -> Dict[str, Any]:
    result = {
        "ok": False,
        "error_code": code,
        "data": data if data is not None else {},
        "message": message,
    }
    result.update(extra)
    return result


@dataclass
class ToolContext:
    user_id: str
    session_id: str
    profile: Dict[str, Any] = field(default_factory=dict)
    last_user_message: str = ""
    emotion_level: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_categories",
            "description": "列出商城在售的部门与品类。用户问“你们卖什么/有什么品类/能买什么”时先调用它，不要只默认美妆。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "按品类、人群、关键词、规格和预算查询真实商品。覆盖美妆、服饰、鞋、箱包、食品饮料、母婴、家居日用。用户让你推荐、问某类商品、给老人/儿童/男士/女士买、或给出预算时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {"type": "string", "description": "部门：美妆/服饰/鞋/箱包/食品饮料/母婴/家居日用"},
                    "category": {"type": "string", "description": "细分类目，如面霜、衬衫、运动鞋、牛奶、纸尿裤、保温杯"},
                    "audience": {"type": "string", "description": "适用人群：老人/儿童/男士/女士/成人/全人群"},
                    "keyword": {"type": "string", "description": "关键词，如无糖、防滑、纯棉、高钙、加绒"},
                    "size": {"type": "string", "description": "尺码，如 XL、42、130"},
                    "color": {"type": "string", "description": "颜色，如黑色、白色"},
                    "flavor": {"type": "string", "description": "口味，如原味、草莓、乌龙茶"},
                    "spec": {"type": "string", "description": "规格，如 500ml、24 包、800g"},
                    "skin_type": {"type": "string", "description": "美妆场景可填：油皮/干皮/敏感肌/混合肌"},
                    "concerns": {"type": "array", "items": {"type": "string"}, "description": "美妆功效诉求，如控油、保湿、修护"},
                    "min_price": {"type": "integer", "description": "最低价"},
                    "max_price": {"type": "integer", "description": "最高价"},
                    "limit": {"type": "integer", "description": "返回数量，1-5，默认 3"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_detail",
            "description": "查询单个商品的完整信息：价格、库存、规格、适用人群、材质/成分、用法和注意事项。用户问细节、尺码、成分、适用人群时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "商品名或商品 ID"}
                },
                "required": ["product_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": "查询某个商品当前真实库存，可指定购买数量判断是否够。不要凭记忆回答库存。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "商品名或商品 ID"},
                    "quantity": {"type": "integer", "description": "想购买的数量，默认 1"}
                },
                "required": ["product_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_products",
            "description": "对比 2-3 个商品的价格、适用人群、规格/成分、库存和注意事项，用于回答“哪个好/有什么区别”。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要对比的商品名，2-3 个"
                    }
                },
                "required": ["product_names"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "按订单号查询当前用户的订单状态、商品、金额、物流单号和售后状态。用户给订单号或问订单进度时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号，格式 DD2026001"}
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_orders",
            "description": "查询当前用户最近的订单列表。用户说“我的订单”“最近买了什么”但没有给订单号时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "可选状态：待发货/已发货/运输中/已签收/已取消"},
                    "limit": {"type": "integer", "description": "返回数量，默认 5"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_logistics",
            "description": "查询订单的物流轨迹、承运商和最新节点。用户问“到哪了/物流怎么不动”时使用，比 query_order 更详细。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"}
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_return_request",
            "description": "为已签收订单登记退货/退款/换货申请。会校验订单归属、签收时间、是否拆封和退货原因。用户明确要退货或反馈质量/过敏问题时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"},
                    "reason": {"type": "string", "description": "退货原因，尽量引用用户原话，如“使用后过敏”“运输破损”“不喜欢”"},
                    "opened": {"type": "boolean", "description": "商品是否已拆封/使用"},
                    "quantity": {"type": "integer", "description": "退货数量，默认 1"}
                },
                "required": ["order_id", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "issue_coupon",
            "description": "给价格犹豫的用户发放专属挽单优惠券。金额最多 20 元，同一用户最多一张。用户说太贵、再考虑、能便宜点，或明确索要优惠时使用；愤怒投诉场景不要用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "description": "优惠券金额，1-20 元，默认 20"},
                    "reason": {"type": "string", "description": "发券原因，如“价格异议”“犹豫未下单”"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_coupons",
            "description": "查询当前用户已领取的优惠券、面额、有效期和状态。用户问“我有什么券/券在哪”时使用。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_member_benefits",
            "description": "查询当前用户的会员等级、积分、专属权益和升级条件。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_promotions",
            "description": "查询当前正在进行的店铺活动、满减、赠品和活动规则。用户问“有什么活动/优惠”时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "可选品类，如防晒、面霜；不填则查全场"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "product_insights",
            "description": "选品/运营分析：按部门查看热销、高退货、低库存、高毛利商品，返回销量、库存、退货率、毛利率和建议。用户问“哪个卖得好/退货率高/库存周转/选品”时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {"type": "string", "description": "可选部门：美妆/服饰/鞋/箱包/食品饮料/母婴/家居日用"},
                    "metric": {"type": "string", "enum": ["top_sales", "high_return", "low_stock", "high_margin"], "description": "分析维度"},
                    "limit": {"type": "integer", "description": "返回数量，默认 5"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "campaign_insights",
            "description": "营销/活动分析：查看优惠券/满减活动的核销、收入、成本和 ROI，给出投放建议。用户问“活动效果/ROI/券核销”时使用。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_faq",
            "description": "查询店铺政策知识库：发货时效、物流、正品、过敏处理、孕妇可用性、退货退款、发票、支付、价格保护、客服时间、修改地址等。政策类问题必须先用它。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "用户问题或关键词"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_routine",
            "description": "根据肤质和诉求生成早晚护肤流程，并给出具体在售商品、顺序、用法和注意事项。用户问“怎么搭配/护肤步骤”时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "skin_type": {"type": "string", "description": "肤质，不填则使用用户画像"},
                    "concerns": {"type": "array", "items": {"type": "string"}, "description": "功效诉求"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "把指定商品加入当前用户购物车，并返回购物车小计。用户说“加购/买这个/来一个”时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "商品名或商品 ID"},
                    "quantity": {"type": "integer", "description": "数量，默认 1"}
                },
                "required": ["product_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_cart",
            "description": "查看当前用户购物车中的商品、数量、小计和总价。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_user_profile",
            "description": "在用户明确提供肤质、诉求、预算或过敏信息时，更新其长期画像。不要把猜测写进画像。",
            "parameters": {
                "type": "object",
                "properties": {
                    "skin_type": {"type": "string", "description": "肤质"},
                    "concerns": {"type": "array", "items": {"type": "string"}, "description": "功效诉求"},
                    "budget": {"type": "integer", "description": "预算上限，元"},
                    "allergies": {"type": "array", "items": {"type": "string"}, "description": "过敏或需避开的成分"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": "查询当前用户的肤质、诉求、预算、过敏史和会员信息。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_human_handoff",
            "description": "创建人工客服工单并转接。仅在用户明确要求人工，或情绪激动、投诉、监管威胁、复杂售后时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "转人工原因，引用用户诉求"},
                    "priority": {"type": "string", "enum": ["normal", "high", "urgent"], "description": "优先级"}
                },
                "required": ["reason"]
            }
        }
    },
]


ALLOWED_TOOL_NAMES = {item["function"]["name"] for item in TOOL_SCHEMAS}


class CommerceToolkit:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        knowledge: KnowledgeBase,
        now_fn: Optional[Any] = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.knowledge = knowledge
        self.data_dir = Path(settings.data_dir)
        self.products: List[Dict[str, Any]] = self._load("products.json")
        self.orders: List[Dict[str, Any]] = self._load("orders.json")
        self.users: List[Dict[str, Any]] = self._load("users.json")
        self.promotions: List[Dict[str, Any]] = self._load("promotions.json")
        self.product_by_id = {product["id"]: product for product in self.products}
        self.product_by_name = {product["name"]: product for product in self.products}
        self.order_by_id = {order["order_id"]: order for order in self.orders}
        self.user_by_id = {user["user_id"]: user for user in self.users}
        self._aliases: List[Tuple[str, Dict[str, Any]]] = []
        for product in self.products:
            for name in [product["name"], product["id"]] + list(product.get("aliases", []) or []):
                self._aliases.append((_norm(name), product))
        self._aliases.sort(key=lambda pair: len(pair[0]), reverse=True)
        self.now_fn = now_fn or self._default_now
        self.erp_client: Optional[HttpCommerceClient] = None
        if getattr(settings, "erp_base_url", None):
            self.erp_client = HttpCommerceClient(
                settings.erp_base_url,
                api_key=getattr(settings, "erp_api_key", None),
                timeout=5.0,
                retries=2,
            )

    def close(self) -> None:
        if self.erp_client is not None:
            self.erp_client.close()

    def _default_now(self) -> datetime:
        if getattr(self.settings, "demo_now", None):
            parsed = _parse_dt(self.settings.demo_now)
            if parsed:
                return parsed
        return datetime.now()

    def _load(self, filename: str) -> List[Dict[str, Any]]:
        path = self.data_dir / filename
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise RuntimeError("缺少业务数据文件：%s" % path)
        except json.JSONDecodeError as exc:
            raise RuntimeError("业务数据格式错误：%s（%s）" % (path, exc))

    # ------------------------------------------------------------------
    # 通用查询
    # ------------------------------------------------------------------
    def get_tools(self) -> List[Dict[str, Any]]:
        return json.loads(json.dumps(TOOL_SCHEMAS, ensure_ascii=False))

    def resolve_product(self, name: str) -> Optional[Dict[str, Any]]:
        if not name:
            return None
        key = _norm(name)
        if key.upper() in self.product_by_id:
            return self.product_by_id[key.upper()]
        if name in self.product_by_name:
            return self.product_by_name[name]
        for alias, product in self._aliases:
            if alias == key:
                return product
        for alias, product in self._aliases:
            if alias in key or key in alias:
                return product
        names = list(self.product_by_name.keys())
        matches = difflib.get_close_matches(name, names, n=1, cutoff=0.55)
        return self.product_by_name.get(matches[0]) if matches else None

    def get_profile(self, user_id: str) -> Dict[str, Any]:
        static = dict(self.user_by_id.get(user_id, {}))
        dynamic = self.store.get_profile(user_id) or {}
        profile = dict(static)
        profile.update(dynamic)
        profile.setdefault("user_id", user_id)
        if not profile.get("member_tier"):
            profile["member_tier"] = "普通会员"
            profile["points"] = 0
        return profile

    @staticmethod
    def _safe_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
        keys = [
            "user_id", "name", "member_tier", "points", "age_group", "gender", "segment",
            "preferred_departments", "skin_type", "concerns", "allergies", "budget",
            "city", "pregnant", "breastfeeding",
        ]
        return {key: profile.get(key) for key in keys if key in profile}

    def _product_view(self, product: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
        view = {
            "id": product["id"],
            "name": product["name"],
            "brand": product.get("brand", ""),
            "department": product.get("department", ""),
            "category": product.get("category", ""),
            "price": product.get("price"),
            "original_price": product.get("original_price"),
            "stock": product.get("stock", 0),
            "available": int(product.get("stock", 0)) > 0,
            "audience": product.get("audience", []),
            "attributes": product.get("attributes", {}),
            "skin_types": product.get("skin_types", []),
            "concerns": product.get("concerns", []),
            "rating": product.get("rating"),
            "reviews": product.get("reviews"),
            "tags": product.get("tags", []),
            "description": product.get("description", ""),
        }
        if reason:
            view["reason"] = reason
        return view

    def _detail_view(self, product: Dict[str, Any]) -> Dict[str, Any]:
        view = self._product_view(product)
        view.update({
            "ingredients": product.get("ingredients", []),
            "usage": product.get("usage", ""),
            "cautions": product.get("cautions", ""),
            "aliases": product.get("aliases", []),
        })
        return view

    @staticmethod
    def _attribute_text(product: Dict[str, Any]) -> str:
        return " ".join([
            product.get("name", ""),
            product.get("department", ""),
            product.get("category", ""),
            product.get("description", ""),
            " ".join(product.get("tags", [])),
            " ".join(product.get("aliases", [])),
            json.dumps(product.get("attributes", {}), ensure_ascii=False),
        ])

    @staticmethod
    def _field_matches(product: Dict[str, Any], field: str, value: str) -> bool:
        if not value:
            return True
        key_map = {"size": "尺码", "color": "颜色", "flavor": "口味", "spec": "规格"}
        attributes = product.get("attributes", {}) or {}
        key = key_map.get(field, field)
        raw = attributes.get(key)
        if field == "size" and raw:
            if isinstance(raw, list):
                tokens = [str(item) for item in raw]
            else:
                tokens = re.split(r"[\s,，、/]+", str(raw))
            if _norm(value) in {_norm(token) for token in tokens if token}:
                return True
            return False
        candidates = [
            str(raw or ""),
            json.dumps(attributes, ensure_ascii=False),
            product.get("name", ""),
            " ".join(product.get("tags", [])),
        ]
        return _norm(value) in _norm(" ".join(candidates))

    def _score_product(
        self,
        product: Dict[str, Any],
        skin_type: Optional[str],
        concerns: List[str],
        keyword: Optional[str],
        category: Optional[str],
        department: Optional[str] = None,
        audience: Optional[str] = None,
    ) -> Tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []
        if department and department == product.get("department"):
            score += 1.8
            reasons.append("属于%s" % department)
        if audience:
            audiences = product.get("audience", [])
            if audience in audiences:
                score += 2.0
                reasons.append("适合%s" % audience)
            elif "全人群" in audiences:
                score += 1.4
                reasons.append("全人群适用")
        skins = product.get("skin_types", [])
        if skin_type:
            if skin_type in skins:
                score += 2.2
                reasons.append("适合%s" % skin_type)
            elif "所有肤质" in skins:
                score += 1.6
                reasons.append("全肤质适用")
            else:
                score -= 2.0
        hits = [concern for concern in concerns if concern in product.get("concerns", [])]
        if hits:
            score += 2.5 * len(hits)
            reasons.append("针对%s" % "、".join(hits[:3]))
        if category and category == product.get("category"):
            score += 2.0
            reasons.append("品类匹配")
        if keyword:
            lowered = _norm(keyword)
            if lowered in _norm(product.get("name", "")):
                score += 3.0
                reasons.append("与关键词「%s」直接匹配" % keyword)
            elif lowered in _norm(self._attribute_text(product)):
                score += 1.2
                reasons.append("与「%s」相关" % keyword)
            else:
                score -= 1.5
        score += float(product.get("rating", 0)) * 0.15
        if int(product.get("stock", 0)) <= 0:
            score -= 5
        return score, list(dict.fromkeys(reasons))

    def _search(
        self,
        skin_type: Optional[str] = None,
        concerns: Optional[List[str]] = None,
        category: Optional[str] = None,
        department: Optional[str] = None,
        audience: Optional[str] = None,
        keyword: Optional[str] = None,
        size: Optional[str] = None,
        color: Optional[str] = None,
        flavor: Optional[str] = None,
        spec: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        limit: int = 3,
        in_stock_only: bool = True,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        concerns = concerns or []
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for product in self.products:
            price = float(product.get("price", 0) or 0)
            if min_price is not None and price < min_price:
                continue
            if max_price is not None and price > max_price:
                continue
            if department and department != product.get("department"):
                continue
            if category and category != product.get("category"):
                continue
            if in_stock_only and int(product.get("stock", 0)) <= 0:
                continue
            if audience:
                audiences = product.get("audience", [])
                if audience not in audiences and "全人群" not in audiences:
                    continue
            skins = product.get("skin_types", [])
            if skin_type and skin_type not in skins and "所有肤质" not in skins:
                continue
            if not all([
                self._field_matches(product, "size", size or ""),
                self._field_matches(product, "color", color or ""),
                self._field_matches(product, "flavor", flavor or ""),
                self._field_matches(product, "spec", spec or ""),
            ]):
                continue
            if keyword and _norm(keyword) not in _norm(self._attribute_text(product)):
                continue
            score, reasons = self._score_product(
                product, skin_type, concerns, keyword, category, department, audience
            )
            scored.append((score, self._product_view(product, "；".join(reasons))))
        scored.sort(key=lambda item: (item[0], item[1].get("rating", 0)), reverse=True)
        relaxed = False
        if concerns and scored:
            exact = [item for item in scored if any(c in item[1].get("concerns", []) for c in concerns)]
            if exact:
                scored = exact
            else:
                relaxed = True
        return [item[1] for item in scored[: max(1, min(5, limit))]], relaxed

    # ------------------------------------------------------------------
    # 工具实现
    # ------------------------------------------------------------------
    def list_categories(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for product in self.products:
            department = product.get("department", "其他")
            item = grouped.setdefault(department, {"department": department, "categories": set(), "products": 0})
            item["categories"].add(product.get("category", ""))
            item["products"] += 1
        departments = []
        for department in ["美妆", "服饰", "鞋", "箱包", "食品饮料", "母婴", "家居日用"]:
            if department in grouped:
                item = grouped[department]
                departments.append({
                    "department": department,
                    "categories": sorted(c for c in item["categories"] if c),
                    "products": item["products"],
                })
        for department, item in grouped.items():
            if department not in {d["department"] for d in departments}:
                departments.append({
                    "department": department,
                    "categories": sorted(c for c in item["categories"] if c),
                    "products": item["products"],
                })
        return _ok(
            {"departments": departments, "count": len(departments)},
            "在售 %d 个部门：%s" % (len(departments), "、".join(d["department"] for d in departments)),
        )

    def search_products(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(
            args,
            [
                "skin_type", "concerns", "category", "department", "audience",
                "keyword", "size", "color", "flavor", "spec",
                "min_price", "max_price", "limit",
            ],
        )
        skin_type = (args.get("skin_type") or "").strip() or None
        concerns = _as_list(args.get("concerns"))
        category = (args.get("category") or "").strip() or None
        department = (args.get("department") or "").strip() or None
        audience = (args.get("audience") or "").strip() or None
        keyword = (args.get("keyword") or "").strip() or None
        size = (args.get("size") or "").strip() or None
        color = (args.get("color") or "").strip() or None
        flavor = (args.get("flavor") or "").strip() or None
        spec = (args.get("spec") or "").strip() or None
        min_price = normalize_int(args.get("min_price"), default=0, minimum=0, maximum=100000) or None
        max_price = normalize_int(args.get("max_price"), default=0, minimum=0, maximum=100000) or None
        limit = normalize_int(args.get("limit"), default=3, minimum=1, maximum=5)
        products, relaxed = self._search(
            skin_type=skin_type,
            concerns=concerns,
            category=category,
            department=department,
            audience=audience,
            keyword=keyword,
            size=size,
            color=color,
            flavor=flavor,
            spec=spec,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
        )
        if not products:
            return _ok(
                {"products": [], "count": 0, "relaxed": False},
                "没有找到完全匹配的商品，可以放宽预算、换一个品类，或去掉尺码/颜色限制。",
            )
        message = "找到 %d 款匹配商品" % len(products)
        if relaxed:
            message += "（没有完全命中功效，已推荐相近选择）"
        return _ok(
            {
                "products": products,
                "count": len(products),
                "relaxed": relaxed,
                "filters": {
                    "department": department,
                    "category": category,
                    "audience": audience,
                    "skin_type": skin_type,
                    "concerns": concerns,
                    "keyword": keyword,
                    "size": size,
                    "color": color,
                    "flavor": flavor,
                    "spec": spec,
                    "max_price": max_price,
                },
            },
            message,
        )

    def get_product_detail(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["product_name"])
        name = str(args.get("product_name", "")).strip()
        product = self.resolve_product(name)
        if not product:
            return _err("PRODUCT_NOT_FOUND", "没有找到「%s」，请确认商品名称。" % name)
        return _ok(self._detail_view(product), "已查询到商品详情")

    def check_stock(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["product_name", "quantity"])
        name = str(args.get("product_name", "")).strip()
        quantity = normalize_int(args.get("quantity"), default=1, minimum=1, maximum=99)
        product = self.resolve_product(name)
        if not product:
            return _err("PRODUCT_NOT_FOUND", "没有找到「%s」。" % name)
        stock = int(product.get("stock", 0))
        enough = stock >= quantity
        message = "库存充足" if enough else "库存不足，当前仅剩 %d 件" % stock
        return _ok(
            {
                "product": product["name"],
                "product_id": product["id"],
                "stock": stock,
                "requested": quantity,
                "enough": enough,
                "shortfall": max(0, quantity - stock),
            },
            message,
        )

    def compare_products(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["product_names"])
        names = _as_list(args.get("product_names"))
        if len(names) < 2:
            return _err("TOO_FEW_PRODUCTS", "至少提供两个商品名称才能对比。")
        products: List[Dict[str, Any]] = []
        missing: List[str] = []
        for name in names[:3]:
            product = self.resolve_product(name)
            if product:
                products.append(product)
            else:
                missing.append(name)
        if len(products) < 2:
            return _err("PRODUCT_NOT_FOUND", "没有找到足够的商品进行对比。", {"missing": missing})
        compare = []
        for product in products:
            compare.append({
                "name": product["name"],
                "department": product.get("department", ""),
                "category": product.get("category", ""),
                "audience": product.get("audience", []),
                "attributes": product.get("attributes", {}),
                "price": product.get("price"),
                "skin_types": product.get("skin_types", []),
                "concerns": product.get("concerns", []),
                "ingredients": product.get("ingredients", []),
                "stock": product.get("stock", 0),
                "rating": product.get("rating"),
                "cautions": product.get("cautions", ""),
            })
        return _ok(
            {"products": compare, "missing": missing},
            "已按价格、适用人群、规格和成分对比 %d 款商品" % len(compare),
        )

    def _get_order(self, order_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        order = self.order_by_id.get((order_id or "").upper())
        if not order or order.get("user_id") != user_id:
            return None
        return order

    def _order_view(self, order: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "order_id": order["order_id"],
            "status": order.get("status"),
            "status_code": order.get("status_code"),
            "items": order.get("items", []),
            "amount": order.get("amount"),
            "discount": order.get("discount", 0),
            "paid": order.get("paid"),
            "carrier": order.get("carrier"),
            "tracking_no": order.get("tracking_no"),
            "created_at": order.get("created_at"),
            "shipped_at": order.get("shipped_at"),
            "delivered_at": order.get("delivered_at"),
            "estimated_delivery": order.get("estimated_delivery"),
            "address_masked": order.get("address_masked"),
            "timeline": list(order.get("timeline", []))[-4:],
            "returnable": order.get("returnable"),
            "return_deadline": order.get("return_deadline"),
            "can_cancel": order.get("status_code") == "pending",
            "note": order.get("note", ""),
        }

    def query_order(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["order_id"])
        order_id = str(args.get("order_id", "")).strip().upper()
        if self.erp_client is not None:
            try:
                remote = self.erp_client.get_order(order_id)
                if remote.get("user_id") == ctx.user_id:
                    return _ok(
                        self._order_view(remote),
                        "订单 %s 当前状态：%s（ERP 实时）" % (order_id, remote.get("status")),
                    )
                return _err("ORDER_NOT_FOUND", "没有查到该订单，请确认订单号是否属于当前账号。")
            except ERPError as exc:
                self.store.log_event(
                    "erp_fallback",
                    user_id=ctx.user_id,
                    session_id=ctx.session_id,
                    payload={"method": "query_order", "code": exc.code, "order_id": order_id},
                )
        order = self._get_order(order_id, ctx.user_id)
        if not order:
            return _err("ORDER_NOT_FOUND", "没有查到该订单，请确认订单号是否属于当前账号。")
        return _ok(self._order_view(order), "订单 %s 当前状态：%s" % (order_id, order.get("status")))

    def list_orders(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["status", "limit"])
        status = (args.get("status") or "").strip()
        limit = normalize_int(args.get("limit"), default=5, minimum=1, maximum=10)
        orders = [order for order in self.orders if order.get("user_id") == ctx.user_id]
        if status:
            orders = [order for order in orders if order.get("status") == status]
        orders.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        data = [
            {
                "order_id": order["order_id"],
                "status": order.get("status"),
                "items": [item.get("name") for item in order.get("items", [])],
                "paid": order.get("paid"),
                "created_at": order.get("created_at"),
                "tracking_no": order.get("tracking_no"),
            }
            for order in orders[:limit]
        ]
        return _ok({"orders": data, "count": len(data)}, "查到 %d 个订单" % len(data))

    def query_logistics(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["order_id"])
        order_id = str(args.get("order_id", "")).strip().upper()
        if self.erp_client is not None:
            try:
                remote_order = self.erp_client.get_order(order_id)
                if remote_order.get("user_id") != ctx.user_id:
                    return _err("ORDER_NOT_FOUND", "没有查到该订单，请确认订单号是否属于当前账号。")
                remote = self.erp_client.get_logistics(order_id)
                tracking = remote.get("tracking_no")
                latest = remote.get("latest") or {}
                return _ok(
                    {
                        "order_id": order_id,
                        "status": remote.get("status"),
                        "carrier": remote.get("carrier"),
                        "tracking_no": tracking,
                        "latest": latest,
                        "timeline": remote.get("timeline", []),
                        "estimated_delivery": remote.get("estimated_delivery"),
                        "note": "ERP 实时物流",
                    },
                    "物流最新节点：%s" % latest.get("detail", latest.get("status", "暂无更新")),
                )
            except ERPError as exc:
                self.store.log_event(
                    "erp_fallback",
                    user_id=ctx.user_id,
                    session_id=ctx.session_id,
                    payload={"method": "query_logistics", "code": exc.code, "order_id": order_id},
                )
        order = self._get_order(order_id, ctx.user_id)
        if not order:
            return _err("ORDER_NOT_FOUND", "没有查到该订单，请确认订单号是否属于当前账号。")
        tracking = order.get("tracking_no")
        if not tracking:
            return _ok(
                {
                    "order_id": order_id,
                    "status": order.get("status"),
                    "tracking_no": None,
                    "timeline": order.get("timeline", []),
                    "message": "订单尚未发货，暂无物流单号。",
                },
                "订单尚未发货，预计 %s 前发出" % (order.get("estimated_delivery") or "按页面时效"),
            )
        timeline = list(order.get("timeline", []))
        latest = timeline[-1] if timeline else {}
        return _ok(
            {
                "order_id": order_id,
                "status": order.get("status"),
                "carrier": order.get("carrier"),
                "tracking_no": tracking,
                "latest": latest,
                "timeline": timeline[-5:],
                "estimated_delivery": order.get("estimated_delivery"),
                "note": order.get("note", ""),
            },
            "物流最新节点：%s" % latest.get("detail", latest.get("status", "暂无更新")),
        )

    def create_return_request(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["order_id", "reason", "opened", "quantity"])
        order_id = str(args.get("order_id", "")).strip().upper()
        reason = str(args.get("reason", "")).strip() or "用户申请退货"
        opened = normalize_bool(args.get("opened"), default=False)
        quantity = normalize_int(args.get("quantity"), default=1, minimum=1, maximum=20)
        order = self._get_order(order_id, ctx.user_id)
        if not order:
            return _err("ORDER_NOT_FOUND", "没有查到该订单，请确认订单号是否属于当前账号。")

        existing = self.store.get_return_by_order(order_id)
        if existing:
            return _ok(
                {
                    "return_id": existing["return_id"],
                    "status": existing["status"],
                    "refund_amount": existing["refund_amount"],
                    "duplicate": True,
                },
                "该订单已有售后单 %s，无需重复提交。" % existing["return_id"],
            )

        status_code = order.get("status_code")
        if status_code == "pending":
            return _err("ORDER_NOT_SHIPPED", "订单还未发货，建议直接在订单页取消，比退货更快。")
        if status_code in {"shipped", "in_transit"}:
            return _err(
                "ORDER_IN_TRANSIT",
                "订单还在运输中，暂时不能登记退货。可以拒收，或签收后再申请；如为破损请签收时拍照留证。",
            )
        if status_code != "delivered":
            return _err("ORDER_NOT_ELIGIBLE", "当前订单状态不支持退货，建议转人工核实。")

        delivered_at = _parse_dt(order.get("delivered_at"))
        now = self.now_fn()
        if not delivered_at:
            return _err("ORDER_DATA_ERROR", "订单签收时间缺失，建议转人工核实。")
        days_since = (now - delivered_at).days
        quality_reason = any(word in reason for word in ["质量", "破损", "过敏", "不适", "错发", "漏发", "过期", "假货"])
        if days_since > self.settings.return_window_days and not quality_reason:
            return _err(
                "RETURN_WINDOW_EXPIRED",
                "该订单签收已超过 %d 天，超出无理由退货期限；如有质量问题可转人工特殊处理。" % self.settings.return_window_days,
                {"delivered_at": order.get("delivered_at"), "days_since": days_since},
            )
        if opened and not quality_reason:
            return _err(
                "OPENED_NOT_RETURNABLE",
                "商品已拆封，按规则不支持七天无理由退货；如果是质量问题或使用不适，可以转人工处理。",
            )

        item = (order.get("items") or [{}])[0]
        unit_price = float(item.get("price", 0) or 0)
        purchased = int(item.get("quantity", 1) or 1)
        refund_quantity = min(quantity, purchased)
        refund_amount = round(min(float(order.get("paid", unit_price * purchased) or 0), unit_price * refund_quantity), 2)
        detail = "原因：%s；拆封：%s；退款路径：原路退回" % (reason, "是" if opened else "否")
        remote_note = ""
        return_id = ""
        if self.erp_client is not None:
            try:
                remote = self.erp_client.create_return(
                    order_id=order_id,
                    reason=reason,
                    opened=opened,
                    quantity=refund_quantity,
                    idempotency_key="return-%s-%s" % (order_id, ctx.session_id),
                )
                return_id = str(remote.get("return_id") or "")
                remote_note = "（ERP 已受理）"
            except ERPError as exc:
                self.store.log_event(
                    "erp_fallback",
                    user_id=ctx.user_id,
                    session_id=ctx.session_id,
                    payload={"method": "create_return", "code": exc.code, "order_id": order_id},
                )
                return_id = ""
        if not return_id:
            return_id = "R%s%s" % (now.strftime("%Y%m%d%H%M%S"), secrets.token_hex(2).upper())
        record = self.store.create_return(
            return_id=return_id,
            order_id=order_id,
            user_id=ctx.user_id,
            reason=reason,
            refund_amount=refund_amount,
            detail=detail,
        )
        return _ok(
            {
                "return_id": record["return_id"],
                "order_id": order_id,
                "status": "待审核",
                "refund_amount": refund_amount,
                "refund_method": "原路退回",
                "quantity": refund_quantity,
                "instructions": "请在订单页填写退货物流单号；质量问题/过敏请保留包装和照片。",
                "estimated_refund": "仓库验收后 1-3 个工作日",
                "quality_case": quality_reason,
                "source": "erp" if remote_note else "local",
            },
            "已登记退货申请 %s，退款预计 %s 元。%s" % (return_id, refund_amount, remote_note),
        )

    def issue_coupon(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["amount", "reason"])
        requested = normalize_int(args.get("amount"), default=20, minimum=1, maximum=999)
        amount = min(requested, self.settings.coupon_max_amount)
        reason = str(args.get("reason", "")).strip() or "价格异议"
        if ctx.emotion_level >= 2:
            return _err("EMOTION_GUARD", "用户情绪激动，先处理问题，不发券。")
        if self.store.count_coupons(ctx.user_id, "retention") >= self.settings.retention_coupon_limit:
            coupons = self.store.list_coupons(ctx.user_id, "active")
            return _err(
                "COUPON_LIMIT_REACHED",
                "该用户已领取过专属优惠券，不能重复发放。",
                {"coupons": coupons[:3], "limit": self.settings.retention_coupon_limit},
            )
        code = "XM" + secrets.token_hex(4).upper()
        coupon_id = "C" + secrets.token_hex(6).upper()
        expires_at = (self.now_fn() + timedelta(days=7)).strftime("%Y-%m-%d")
        self.store.add_coupon(
            coupon_id=coupon_id,
            user_id=ctx.user_id,
            code=code,
            amount=amount,
            coupon_type="retention",
            reason=reason,
            expires_at=expires_at,
        )
        return _ok(
            {
                "code": code,
                "amount": amount,
                "requested_amount": requested,
                "adjusted": requested > amount,
                "expires_at": expires_at,
                "scope": "全场正价商品，单笔限用一张",
                "note": "不与其他优惠券叠加，特价商品可能不参与",
            },
            "已发放 %d 元专属优惠券，券码 %s，有效期至 %s。" % (amount, code, expires_at),
        )

    def list_coupons(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        coupons = self.store.list_coupons(ctx.user_id)
        active = [coupon for coupon in coupons if coupon.get("status") == "active"]
        return _ok(
            {"coupons": coupons[:10], "active_count": len(active)},
            "当前有 %d 张可用优惠券" % len(active),
        )

    def get_member_benefits(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        profile = self.get_profile(ctx.user_id)
        tier = profile.get("member_tier", "普通会员")
        points = int(profile.get("points", 0) or 0)
        benefits = {
            "普通会员": ["消费 1 元积 1 分", "生日月 10 元券"],
            "白银会员": ["消费 1 元积 1 分", "生日月 20 元券", "每月 1 张运费券"],
            "黄金会员": ["消费 1 元积 1.5 分", "生日月 30 元券", "每月 2 张运费券", "会员日双倍积分"],
            "铂金会员": ["消费 1 元积 2 分", "生日月 50 元券", "专属客服", "新品优先购", "会员日双倍积分"],
        }
        next_tier = None
        if tier in {"普通会员", "白银会员"}:
            next_tier = {"name": "黄金会员", "points_needed": max(0, 1000 - points)}
        elif tier == "黄金会员":
            next_tier = {"name": "铂金会员", "points_needed": max(0, 3000 - points)}
        return _ok(
            {
                "tier": tier,
                "points": points,
                "benefits": benefits.get(tier, benefits["普通会员"]),
                "next_tier": next_tier,
                "note": "积分在确认收货后发放，退款订单会扣回",
            },
            "%s，当前 %d 积分" % (tier, points),
        )

    def get_promotions(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["category"])
        category = (args.get("category") or "").strip()
        today = self.now_fn().strftime("%Y-%m-%d")
        active = []
        for promo in self.promotions:
            if promo.get("start_at") and promo["start_at"] > today:
                continue
            if promo.get("end_at") and promo["end_at"] < today:
                continue
            if category and promo.get("category") not in {"全场", category}:
                continue
            active.append(promo)
        return _ok({"promotions": active, "count": len(active)}, "当前有 %d 个进行中的活动" % len(active))

    def product_insights(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["department", "metric", "limit"])
        department = (args.get("department") or "").strip()
        metric = (args.get("metric") or "top_sales").strip()
        if metric not in {"top_sales", "high_return", "low_stock", "high_margin"}:
            metric = "top_sales"
        limit = normalize_int(args.get("limit"), default=5, minimum=1, maximum=10)
        products = [
            product for product in self.products
            if not department or product.get("department") == department
        ]

        def days_of_inventory(product: Dict[str, Any]) -> float:
            daily = max(float(product.get("sales_30d", 0) or 0) / 30.0, 0.1)
            return round(float(product.get("stock", 0) or 0) / daily, 1)

        key_map = {
            "top_sales": lambda item: float(item.get("sales_30d", 0) or 0),
            "high_return": lambda item: float(item.get("return_rate", 0) or 0),
            "low_stock": lambda item: days_of_inventory(item),
            "high_margin": lambda item: float(item.get("gross_margin", 0) or 0),
        }
        products.sort(key=key_map[metric], reverse=metric != "low_stock")
        advice_map = {
            "top_sales": "优先保证库存，适合做主推/关联推荐。",
            "high_return": "检查尺码/质量/详情页描述，必要时下架或换供应商。",
            "low_stock": "库存周转快，建议补货或做限购，避免超卖。",
            "high_margin": "适合做组合装/提升曝光，但注意别牺牲退货率。",
        }
        items = [
            {
                "id": product.get("id"),
                "name": product.get("name"),
                "department": product.get("department"),
                "price": product.get("price"),
                "stock": product.get("stock"),
                "sales_30d": product.get("sales_30d"),
                "return_rate": product.get("return_rate"),
                "gross_margin": product.get("gross_margin"),
                "days_of_inventory": days_of_inventory(product),
            }
            for product in products[:limit]
        ]
        return _ok(
            {
                "metric": metric,
                "department": department or "全部",
                "items": items,
                "advice": advice_map[metric],
                "data_note": "mock 运营数据，用于演示选品/运营分析口径",
            },
            "按 %s 返回 %d 个商品" % (metric, len(items)),
        )

    def campaign_insights(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        campaigns = []
        for promo in self.promotions:
            revenue = float(promo.get("revenue", 0) or 0)
            cost = float(promo.get("cost", 0) or 0)
            roi = round(revenue / cost, 2) if cost else 0.0
            if not cost:
                advice = "缺少成本数据，先小流量测试再放量。"
            elif roi >= 1.5:
                advice = "ROI 健康，可加预算或扩人群。"
            elif roi >= 0.8:
                advice = "ROI 一般，优化素材/人群/门槛后再放量。"
            else:
                advice = "ROI 偏低，建议收缩预算或换品。"
            campaigns.append({
                "id": promo.get("id"),
                "title": promo.get("title"),
                "redeemed": promo.get("redeemed", 0),
                "revenue": revenue,
                "cost": cost,
                "roi": roi,
                "advice": advice,
            })
        campaigns.sort(key=lambda item: item["roi"], reverse=True)
        return _ok(
            {"campaigns": campaigns, "count": len(campaigns), "data_note": "mock 营销数据"},
            "已分析 %d 个活动的核销与 ROI" % len(campaigns),
        )

    def search_faq(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["query"])
        query = str(args.get("query", "")).strip()
        if not query:
            return _err("EMPTY_QUERY", "请提供要查询的问题。")
        matches = self.knowledge.search(query, top_k=3, min_score=0.08)
        if not matches:
            return _err(
                "FAQ_NOT_FOUND",
                "知识库没有找到明确答案，建议转人工确认，不要猜测。",
                {"query": query},
            )
        top = matches[0]
        return _ok(
            {
                "question": top.entry.question,
                "answer": top.entry.answer,
                "category": top.entry.category,
                "faq_id": top.entry.id,
                "sources": [match.entry.id for match in matches],
                "related": [
                    {"question": match.entry.question, "score": match.score}
                    for match in matches[1:]
                ],
            },
            "命中知识库：%s" % top.entry.question,
        )

    def recommend_routine(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["skin_type", "concerns"])
        profile = self.get_profile(ctx.user_id)
        skin = (args.get("skin_type") or profile.get("skin_type") or "").strip()
        concerns = _as_list(args.get("concerns")) or list(profile.get("concerns", []) or [])
        picks: List[Tuple[str, Dict[str, Any]]] = []

        def pick(category: str) -> Optional[Dict[str, Any]]:
            products, _ = self._search(
                skin_type=skin or None,
                concerns=concerns,
                category=category,
                limit=1,
            )
            if products:
                product = self.resolve_product(products[0]["name"])
                if product:
                    picks.append((category, product))
                    return product
            return None

        cleanser = pick("洁面")
        serum = pick("精华")
        moisturizer = pick("面霜")
        sunscreen = pick("防晒")
        eye = pick("眼霜") if any(term in concerns for term in ["抗老", "细纹", "黑眼圈"]) else None
        remover = pick("卸妆") if any(term in concerns for term in ["卸妆", "清洁"]) or "卸妆" in ctx.last_user_message else None

        if not any([cleanser, serum, moisturizer, sunscreen]):
            return _err("NO_ROUTINE", "暂时没有找到匹配的完整流程，建议放宽预算或转人工搭配。")

        def step(time_name: str, order: int, label: str, product: Optional[Dict[str, Any]]) -> Dict[str, Any]:
            return {
                "time": time_name,
                "order": order,
                "step": label,
                "product": product.get("name") if product else None,
                "product_id": product.get("id") if product else None,
                "price": product.get("price") if product else None,
                "usage": product.get("usage", "") if product else "",
                "reason": "、".join(product.get("concerns", [])[:3]) if product else "",
            }

        am = [
            step("早", 1, "清洁", cleanser),
            step("早", 2, "精华", serum),
            step("早", 3, "保湿", moisturizer),
            step("早", 4, "防晒", sunscreen),
        ]
        pm = [
            step("晚", 1, "卸妆（有淡妆/防晒时）", remover),
            step("晚", 2, "清洁", cleanser),
            step("晚", 3, "精华", serum),
            step("晚", 4, "眼霜", eye),
            step("晚", 5, "保湿", moisturizer),
        ]
        warnings = ["首次使用新产品先做耳后测试，敏感肌隔天建立耐受。"]
        if any(term in concerns for term in ["痘痘", "闭口"]):
            warnings.append("痘痘急性期不要叠加多种酸类，避免过度清洁。")
        if profile.get("pregnant") or profile.get("breastfeeding"):
            warnings.append("孕期/哺乳期请避开视黄醇、水杨酸，使用前咨询医生。")
        total = sum(int(product.get("price", 0)) for _, product in picks)
        return _ok(
            {
                "skin_type": skin or "未提供",
                "concerns": concerns,
                "morning": [item for item in am if item["product"]],
                "evening": [item for item in pm if item["product"]],
                "estimated_total": total,
                "warnings": warnings,
            },
            "已生成早晚护肤流程，预计整套 %d 元" % total,
        )

    def add_to_cart(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["product_name", "quantity"])
        name = str(args.get("product_name", "")).strip()
        quantity = normalize_int(args.get("quantity"), default=1, minimum=1, maximum=99)
        product = self.resolve_product(name)
        if not product:
            return _err("PRODUCT_NOT_FOUND", "没有找到「%s」。" % name)
        if int(product.get("stock", 0)) < quantity:
            return _err(
                "INSUFFICIENT_STOCK",
                "库存不足，当前仅剩 %d 件。" % int(product.get("stock", 0)),
                {"stock": product.get("stock"), "requested": quantity},
            )
        self.store.add_cart_item(ctx.user_id, product["id"], quantity)
        cart = self.view_cart({}, ctx)
        data = cart.get("data", {})
        data["added"] = {"name": product["name"], "quantity": quantity, "price": product["price"]}
        return _ok(data, "已把 %s × %d 加入购物车。" % (product["name"], quantity))

    def view_cart(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        rows = self.store.get_cart(ctx.user_id)
        items = []
        total = 0
        for row in rows:
            product = self.product_by_id.get(row["product_id"])
            if not product:
                continue
            subtotal = int(product.get("price", 0)) * int(row["quantity"])
            total += subtotal
            items.append({
                "product_id": product["id"],
                "name": product["name"],
                "price": product.get("price"),
                "quantity": int(row["quantity"]),
                "subtotal": subtotal,
                "stock": product.get("stock", 0),
            })
        return _ok(
            {"items": items, "count": len(items), "total": total},
            "购物车共 %d 件商品，合计 %d 元" % (len(items), total),
        )

    def update_user_profile(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["skin_type", "concerns", "budget", "allergies"])
        profile = self.get_profile(ctx.user_id)
        if args.get("skin_type"):
            profile["skin_type"] = str(args["skin_type"]).strip()
        if args.get("concerns"):
            profile["concerns"] = list(dict.fromkeys(list(profile.get("concerns", []) or []) + _as_list(args["concerns"])))
        if args.get("budget") is not None:
            profile["budget"] = normalize_int(args.get("budget"), default=0, minimum=0, maximum=100000)
        if args.get("allergies"):
            profile["allergies"] = list(dict.fromkeys(list(profile.get("allergies", []) or []) + _as_list(args["allergies"])))
        self.store.save_profile(ctx.user_id, profile)
        return _ok(self._safe_profile(profile), "已更新用户画像")

    def get_user_profile(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        return _ok(self._safe_profile(self.get_profile(ctx.user_id)), "已查询用户画像")

    def request_human_handoff(self, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        args = clean_arguments(args, ["reason", "priority"])
        reason = str(args.get("reason", "")).strip() or "用户要求人工协助"
        priority = str(args.get("priority", "normal")).lower()
        if priority not in {"normal", "high", "urgent"}:
            priority = "normal"
        existing = self.store.get_open_handoff(ctx.session_id)
        if existing:
            return _ok(
                {
                    "ticket_id": existing["ticket_id"],
                    "priority": existing["priority"],
                    "status": existing["status"],
                    "duplicate": True,
                },
                "已有处理中的工单 %s" % existing["ticket_id"],
            )
        ticket_id = "H%s%s" % (self.now_fn().strftime("%Y%m%d%H%M%S"), secrets.token_hex(2).upper())
        record = self.store.create_handoff(
            ticket_id=ticket_id,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            reason=reason,
            priority=priority,
            context={
                "profile": self._safe_profile(ctx.profile),
                "last_user_message": ctx.last_user_message,
                "emotion_level": ctx.emotion_level,
            },
        )
        return _ok(record, "已创建人工工单 %s" % ticket_id)

    # ------------------------------------------------------------------
    # 分发
    # ------------------------------------------------------------------
    def execute(self, name: str, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        start = time.perf_counter()
        handler = getattr(self, name, None)
        if name not in ALLOWED_TOOL_NAMES or not callable(handler):
            result = _err("UNKNOWN_TOOL", "未知工具：%s" % name)
        else:
            try:
                result = handler(args or {}, ctx)
            except Exception as exc:  # 不把内部异常暴露给模型/用户
                result = _err("TOOL_ERROR", "工具执行失败，请稍后重试或转人工。")
                self.store.log_event(
                    "tool_error",
                    user_id=ctx.user_id,
                    session_id=ctx.session_id,
                    payload={"tool": name, "args": args, "error": type(exc).__name__},
                )
        result["tool"] = name
        result["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
        return result
