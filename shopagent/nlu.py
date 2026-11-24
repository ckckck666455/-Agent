"""轻量 NLU：意图、实体与用户画像抽取。

规则层负责“稳定、可解释、零成本”的部分，LLM 负责开放表达。
即使接入大模型，意图和实体仍会被记录到审计日志，便于分析失败案例。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .schemas import IntentResult


ORDER_RE = re.compile(r"\bDD\d{7}\b", re.IGNORECASE)

SKIN_PATTERNS: List[Tuple[str, List[str]]] = [
    ("油皮", ["大油皮", "油性肌肤", "油性皮肤", "油皮", "T区油", "t区油", "出油多"]),
    ("干皮", ["沙漠皮", "干性肌肤", "干性皮肤", "干皮", "起皮", "紧绷"]),
    ("敏感肌", ["敏感肌", "敏感肌肤", "敏肌", "屏障受损", "容易泛红"]),
    ("混合肌", ["混合肌", "混油皮", "混干皮", "混合性肌肤", "混合性皮肤"]),
    ("中性", ["中性肌", "中性皮肤"]),
    ("痘痘肌", ["痘痘肌", "痘肌", "易长痘"]),
]

CONCERN_PATTERNS: List[Tuple[str, List[str]]] = [
    ("控油", ["控油", "出油", "油光", "T区油", "t区油", "T区特别油", "t区特别油", "特别油", "油田"]),
    ("痘痘", ["痘痘", "长痘", "爆痘", "痘肌", "祛痘"]),
    ("闭口", ["闭口", "粉刺"]),
    ("黑头", ["黑头"]),
    ("毛孔", ["毛孔", "毛孔粗大"]),
    ("保湿", ["保湿", "干燥", "缺水", "起皮", "紧绷", "补水"]),
    ("修护", ["修护", "屏障", "受损", "维稳"]),
    ("泛红", ["泛红", "红血丝", "刺痛", "敏感"]),
    ("提亮", ["提亮", "暗沉", "美白", "肤色不均", "痘印", "熬夜"]),
    ("抗老", ["抗老", "细纹", "皱纹", "紧致", "松弛", "初老"]),
    ("黑眼圈", ["黑眼圈", "眼袋", "浮肿"]),
    ("防晒", ["防晒", "晒黑", "紫外线"]),
    ("清洁", ["清洁", "洗面奶", "洁面"]),
    ("卸妆", ["卸妆", "淡妆", "浓妆"]),
    ("粗糙", ["粗糙", "鸡皮", "身体干燥"]),
]

CATEGORY_TERMS = ["面霜", "精华", "洁面", "洗面奶", "防晒", "面膜", "眼霜", "身体乳", "卸妆"]

DEPARTMENT_PATTERNS: List[Tuple[str, List[str]]] = [
    ("美妆", ["美妆", "护肤", "面霜", "精华", "洁面", "洗面奶", "防晒", "面膜", "眼霜", "身体乳", "卸妆"]),
    ("服饰", ["服饰", "衣服", "衬衫", "卫衣", "外套", "马甲", "开衫", "家居服", "T恤", "t恤", "裤", "裙"]),
    ("鞋", ["运动鞋", "跑鞋", "皮鞋", "靴", "乐福鞋", "健步鞋", "童鞋", "鞋"]),
    ("箱包", ["箱包", "书包", "双肩包", "托特包", "背包", "手提包", "行李箱"]),
    ("食品饮料", ["食品饮料", "饮料", "茶", "果汁", "牛奶", "奶粉", "咖啡", "矿泉水", "零食", "饼干", "坚果", "奶酪", "面包", "食品"]),
    ("母婴", ["母婴", "纸尿裤", "尿不湿", "婴儿", "宝宝", "奶瓶", "儿童牙膏"]),
    ("家居日用", ["家居日用", "纸巾", "抽纸", "洗衣液", "垃圾袋", "保温杯", "雨伞", "拖鞋", "家居"]),
]

AUDIENCE_PATTERNS: List[Tuple[str, List[str]]] = [
    ("老人", ["老人", "老年", "爷爷", "奶奶", "外公", "外婆", "父母", "长辈", "爸妈", "银发"]),
    ("儿童", ["儿童", "小孩", "孩子", "宝宝", "婴儿", "小朋友", "学生", "儿子", "女儿", "幼儿"]),
    ("男士", ["男士", "男生", "男人", "老公", "爸爸", "父亲", "男朋友", "男友"]),
    ("女士", ["女士", "女生", "女人", "老婆", "妈妈", "母亲", "女朋友", "女友"]),
    ("全人群", ["全家", "家庭", "通用", "所有人", "全家用"]),
]


RETURN_TERMS = ["退货", "退款", "换货", "售后", "退换", "退钱"]
POLICY_TERMS = [
    "发货", "物流", "快递", "正品", "防伪", "过敏", "孕妇", "哺乳", "保质期", "发票",
    "支付", "价格保护", "价保", "客服时间", "拆封", "七天", "小样", "赠品", "修改地址",
    "取消订单", "投诉渠道", "儿童", "测试", "叠加", "积分怎么", "怎么退", "退货流程",
    "退款多久", "多久到账", "能退吗", "可以退吗", "支持退", "运费", "配送", "包邮",
    "几点", "在线时间", "人工客服", "什么时候在线",
    "怀孕", "孕期", "哺乳", "备孕",
]
DETAIL_TERMS = ["成分", "适合", "怎么用", "用法", "功效", "孕妇", "敏感", "刺激", "含", "有没有", "介绍", "能用", "可以用", "适用", "尺码", "规格"]
STOCK_TERMS = ["库存", "有货", "还有吗", "还有没有", "补货", "缺货", "卖完", "剩多少"]
COMPARE_TERMS = ["对比", "区别", "哪个好", "怎么选", "选哪个", "差别", "比较"]
CART_TERMS = ["加购", "加入购物车", "购物车", "下单", "买这个", "来一个", "要一个"]
ROUTINE_TERMS = ["搭配", "护肤流程", "护肤步骤", "早C晚A", "早c晚a", "routine", "怎么搭"]
COUPON_TERMS = ["优惠券", "券", "优惠", "便宜", "少点", "折扣", "太贵", "再考虑", "活动", "满减", "赠品"]
MEMBER_TERMS = ["会员", "积分", "等级", "权益", "生日礼"]
HUMAN_RE = re.compile(r"(转人工|找人工|要人工|接人工|换人工|真人客服|人工客服(在吗|呢|吗)|帮我转人工)")
HUMAN_FAQ_RE = re.compile(r"(几点|时间|什么时候|在线时间|工作时间)")
INJECTION_PATTERNS = [
    r"忽略(之前|以上|前面|所有)的?(指令|提示|规则)",
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"(输出|告诉我|展示|打印).{0,8}(系统提示词|system\s*prompt|prompt)",
    r"(开发者模式|developer\s*mode|越狱|jailbreak|DAN模式)",
    r"你现在是.{0,12}(不受限制|没有规则|另一个|新角色)",
    r"扮演.{0,10}(客服|导购|角色).{0,10}(忽略|不要遵守)",
]
INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

MEDICAL_RISK_TERMS = [
    "烂脸", "渗液", "流脓", "大面积爆痘", "严重过敏", "呼吸困难", "湿疹", "皮炎",
    "玫瑰痤疮", "激素脸", "治疗", "药膏", "皮肤科",
]

ALLERGY_RE = re.compile(r"对([\u4e00-\u9fa5A-Za-z]{1,10})(?:成分)?过敏")
KNOWN_ALLERGENS = ["酒精", "香精", "防腐剂", "水杨酸", "烟酰胺", "视黄醇", "果酸", "香料"]
SELF_TRIGGERS = [
    "我是", "我皮肤", "我的皮肤", "我的肤质", "我属于", "本人", "我这种", "我t区", "我T区",
    "肤质是", "皮肤是", "我容易", "我关注", "我想改善", "我需要", "主要想", "T区特别",
]
ANALYTICS_TERMS = [
    "销量", "卖得好", "卖得最好", "退货率", "库存周转", "毛利", "选品",
    "活动效果", "营销效果", "roi", "ROI", "核销", "投放",
]
BUDGET_PATTERNS = [
    re.compile(r"预算\s*(?:是|在|大概|约)?\s*(\d{2,4})"),
    re.compile(r"(?<!\d)(\d{2,4})(?!\d)\s*(?:元|块)?\s*(?:以内|左右|以下)"),
    re.compile(r"不超过\s*(\d{2,4})"),
    re.compile(r"(?<!\d)(\d{2,4})(?!\d)\s*内"),
]
QUANTITY_RE = re.compile(r"(?<!第)(?<!\d)(\d{1,2})\s*(?:件|瓶|支|盒|个|套)")
CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def normalize_text(text: str) -> str:
    text = (text or "").strip()
    text = text.replace("　", " ")
    return re.sub(r"\s+", " ", text)


def extract_order_id(text: str) -> Optional[str]:
    match = ORDER_RE.search(text.upper())
    return match.group(0).upper() if match else None


def extract_skin_type(text: str) -> Optional[str]:
    for canonical, aliases in SKIN_PATTERNS:
        if any(alias.lower() in text.lower() for alias in aliases):
            return canonical
    return None


def extract_concerns(text: str) -> List[str]:
    result: List[str] = []
    lowered = text.lower()
    for canonical, aliases in CONCERN_PATTERNS:
        if any(alias.lower() in lowered for alias in aliases):
            if canonical not in result:
                result.append(canonical)
    return result


def extract_budget(text: str) -> Optional[int]:
    for pattern in BUDGET_PATTERNS:
        for match in pattern.finditer(text):
            try:
                value = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if 20 <= value <= 5000:
                return value
    if "百元内" in text or "一百以内" in text:
        return 100
    if "两百以内" in text:
        return 200
    return None


def extract_quantity(text: str) -> int:
    match = QUANTITY_RE.search(text)
    if match:
        try:
            return max(1, min(99, int(match.group(1))))
        except ValueError:
            pass
    for char, value in CN_NUM.items():
        if re.search(r"第\s*%s\s*(?:件|瓶|支|盒|个|套)" % char, text):
            continue
        if re.search(r"%s\s*(?:件|瓶|支|盒|个|套)" % char, text):
            return value
    return 1


def extract_category(text: str) -> Optional[str]:
    for term in CATEGORY_TERMS:
        if term in text:
            return "洁面" if term == "洗面奶" else term
    return None


def extract_department(text: str) -> Optional[str]:
    lowered = text.lower()
    if "拖鞋" in lowered:
        return "家居日用"
    for department, aliases in DEPARTMENT_PATTERNS:
        if any(alias.lower() in lowered for alias in aliases):
            return department
    return None


def extract_audience(text: str) -> Optional[str]:
    lowered = text.lower()
    for audience, aliases in AUDIENCE_PATTERNS:
        if any(alias.lower() in lowered for alias in aliases):
            return audience
    return None


def extract_allergies(text: str) -> List[str]:
    result: List[str] = []
    invalid = {"我", "它", "这个", "产品", "皮肤", "用了", "使用", "涂了", "擦了", "可能", "有点", "好像", "东西"}
    for match in ALLERGY_RE.finditer(text):
        value = match.group(1).strip()
        if value and value not in invalid and value not in result:
            result.append(value)
    # “酒精过敏”“香精过敏”等没有“对”字的表达，只认已知成分，避免把“用了过敏”误判成过敏原
    for term in KNOWN_ALLERGENS:
        if (term + "过敏") in text or (term + "不耐受") in text:
            if term not in result:
                result.append(term)
    for term in KNOWN_ALLERGENS:
        if re.search(r"(?:避开|不能用|不要用).{0,4}%s" % term, text):
            if term not in result:
                result.append(term)
    return result


class NLU:
    def __init__(self, products: List[Dict[str, Any]]) -> None:
        self.products = products
        self._mentions: List[Tuple[str, str]] = []
        for product in products:
            names = [product.get("name", ""), product.get("id", "")]
            names.extend(product.get("aliases", []) or [])
            for name in names:
                if name:
                    self._mentions.append((name.lower(), product["name"]))
        # 长名称优先，避免“面霜”抢先匹配“修护保湿面霜”
        self._mentions.sort(key=lambda pair: len(pair[0]), reverse=True)

    def extract_product_mentions(self, text: str) -> List[Dict[str, Any]]:
        lowered = text.lower()
        found: List[str] = []
        for mention, canonical in self._mentions:
            if mention in lowered and canonical not in found:
                found.append(canonical)
        by_name = {p["name"]: p for p in self.products}
        return [by_name[name] for name in found if name in by_name]

    def extract_entities(self, text: str) -> Dict[str, Any]:
        products = self.extract_product_mentions(text)
        return {
            "order_id": extract_order_id(text),
            "skin_type": extract_skin_type(text),
            "concerns": extract_concerns(text),
            "budget": extract_budget(text),
            "category": extract_category(text),
            "department": extract_department(text),
            "audience": extract_audience(text),
            "products": [p["name"] for p in products],
            "quantity": extract_quantity(text),
            "allergies": extract_allergies(text),
        }

    @staticmethod
    def is_prompt_injection(text: str) -> bool:
        return any(pattern.search(text) for pattern in INJECTION_RE)

    @staticmethod
    def is_explicit_human(text: str) -> bool:
        if HUMAN_FAQ_RE.search(text) and "人工" in text:
            return False
        return bool(HUMAN_RE.search(text))

    @staticmethod
    def is_medical_risk(text: str) -> bool:
        return _contains_any(text, MEDICAL_RISK_TERMS)

    def classify(self, text: str) -> IntentResult:
        lowered = text.lower()
        entities = self.extract_entities(text)
        products = entities["products"]
        order_id = entities["order_id"]
        secondary: List[str] = []

        def result(intent: str, confidence: float, extra: Optional[Dict[str, Any]] = None) -> IntentResult:
            data = dict(entities)
            if extra:
                data.update(extra)
            return IntentResult(intent=intent, confidence=confidence, entities=data, secondary=secondary)

        if self.is_prompt_injection(text):
            return result("prompt_injection", 0.99)
        if self.is_explicit_human(text):
            return result("human", 0.98)
        if _contains_any(lowered, ["你们卖什么", "卖什么", "有什么品类", "有哪些品类", "有什么商品", "商品目录", "能买什么"]):
            return result("catalog", 0.9)
        if _contains_any(lowered, ANALYTICS_TERMS):
            return result("analytics", 0.88)

        # 售后：有订单号时优先级最高；没有订单号但明确要退货，也进入售后
        policy_question = _contains_any(lowered, POLICY_TERMS) and not order_id
        after_sales_words = _contains_any(lowered, RETURN_TERMS)
        if after_sales_words and (order_id or not policy_question):
            return result("after_sales", 0.9, {"return_reason": self.extract_return_reason(text)})

        # 物流 / 订单
        logistics_words = _contains_any(lowered, ["物流", "快递", "到哪", "运单", "签收", "派送"])
        if order_id and logistics_words:
            return result("logistics", 0.95)
        if order_id or _contains_any(lowered, ["订单", "订单号", "我的包裹"]):
            if after_sales_words:
                return result("after_sales", 0.9, {"return_reason": self.extract_return_reason(text)})
            return result("order_query", 0.92)

        # 优惠 / 会员
        if _contains_any(lowered, ["积分怎么", "会员规则", "优惠券叠加", "怎么用券"]):
            return result("faq", 0.85)
        if _contains_any(lowered, MEMBER_TERMS):
            return result("member", 0.85)
        if _contains_any(lowered, ["太贵", "便宜点", "少点", "优惠点", "再考虑", "打个折", "能少"]):
            return result("coupon", 0.9)
        if "券" in lowered and _contains_any(lowered, ["叠加", "怎么用", "规则", "有效期", "能用吗", "怎么领"]):
            return result("faq", 0.85)
        if re.search(r"(发|给|领|要|来|送).{0,6}(一张|张|个)?券", lowered) or "再来一张" in lowered:
            return result("coupon", 0.9)
        if _contains_any(lowered, ["优惠券", "优惠", "活动", "满减", "券", "赠品"]):
            return result("promotion", 0.8)

        # 商品对比 / 库存 / 详情
        if _contains_any(lowered, COMPARE_TERMS) and len(products) >= 2:
            return result("comparison", 0.9)
        if _contains_any(lowered, STOCK_TERMS) and products:
            return result("stock", 0.9)
        if products and _contains_any(lowered, DETAIL_TERMS):
            return result("product_detail", 0.85)
        if _contains_any(lowered, ["对比", "区别", "哪个好", "怎么选", "选哪个"]):
            return result("comparison", 0.7)

        # 购物车 / 搭配
        if _contains_any(lowered, CART_TERMS):
            return result("cart", 0.8)
        if _contains_any(lowered, ROUTINE_TERMS):
            return result("routine", 0.85)

        # FAQ：政策类问题优先于泛导购
        if _contains_any(lowered, POLICY_TERMS):
            return result("faq", 0.8)

        # 售前导购
        presale_terms = ["推荐", "买", "选", "适合", "送", "有没有", "想要", "需要", "来一", "来点"]
        if (_contains_any(lowered, presale_terms)
                or entities["skin_type"] or entities["concerns"]
                or entities["department"] or entities["audience"]):
            return result("pre_sales", 0.78)
        if _contains_any(lowered, ["你好", "您好", "在吗", "嗨", "hello", "hi", "早上好", "晚上好"]):
            return result("greeting", 0.85)
        if _contains_any(lowered, ["谢谢", "感谢", "辛苦了", "好的"]):
            return result("thanks", 0.8)
        if _contains_any(lowered, ["再见", "拜拜", "没事了"]):
            return result("goodbye", 0.8)
        return result("unknown", 0.3)

    @staticmethod
    def extract_return_reason(text: str) -> str:
        if _contains_any(text, ["过敏", "泛红", "刺痛", "痒", "红肿"]):
            return "使用后过敏/不适"
        if _contains_any(text, ["破损", "碎了", "漏了", "压坏"]):
            return "运输破损"
        if _contains_any(text, ["错发", "发错", "漏发", "少发"]):
            return "错发/漏发"
        if _contains_any(text, ["不喜欢", "买错", "不合适", "不想要"]):
            return "不喜欢/买错"
        if _contains_any(text, ["质量", "假货", "过期"]):
            return "质量问题"
        return "用户申请退货"

    @staticmethod
    def extract_profile_facts(text: str, current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        profile = dict(current or {})
        updates: Dict[str, Any] = {}
        stripped = text.strip()
        self_disclosed = any(trigger.lower() in text.lower() for trigger in SELF_TRIGGERS)
        starts_with_skin = bool(re.match(r"^(油皮|干皮|敏感肌|混合肌|痘痘肌|中性肌)", stripped))

        skin_type = extract_skin_type(text)
        if skin_type and (self_disclosed or starts_with_skin):
            updates["skin_type"] = skin_type
            profile["skin_type"] = skin_type

        if self_disclosed or starts_with_skin:
            concerns = extract_concerns(text)
            if concerns:
                merged = list(dict.fromkeys(list(profile.get("concerns", []) or []) + concerns))
                updates["concerns"] = merged
                profile["concerns"] = merged

        budget = extract_budget(text)
        if budget:
            updates["budget"] = budget
            profile["budget"] = budget
        allergies = extract_allergies(text)
        if allergies:
            merged_allergies = list(dict.fromkeys(list(profile.get("allergies", []) or []) + allergies))
            updates["allergies"] = merged_allergies
            profile["allergies"] = merged_allergies
        if _contains_any(text, ["怀孕", "孕期", "备孕"]):
            updates["pregnant"] = True
        if _contains_any(text, ["哺乳", "母乳"]):
            updates["breastfeeding"] = True
        if self_disclosed:
            if _contains_any(text, ["我是老人", "我年纪大", "我六十", "我七十", "我八十"]):
                updates["age_group"] = "老人"
                profile["age_group"] = "老人"
            elif _contains_any(text, ["我是男的", "我是男生", "本人男"]):
                updates["gender"] = "男"
                profile["gender"] = "男"
            elif _contains_any(text, ["我是女的", "我是女生", "本人女"]):
                updates["gender"] = "女"
                profile["gender"] = "女"
        return updates
