# Coze / Dify 可视化工作流设计

> 目的：给 JD 的“Coze / 百度智能体 / 钉钉 / 企微 Agent / 低代码”一个可展示证据。  
> 建议真搭一遍，截图放作品集；下面是可以直接照着配的节点。

## 1. 工作流

```text
开始
 → 变量初始化（user_id / session_id / message）
 → 意图分类（LLM）
 → 知识库检索（RAG）
 → 条件分支
     ├─ 订单/物流 → HTTP 请求（ERP/OMS）
     ├─ 售后 → 条件判断（订单状态/拆封/原因）→ HTTP 退货
     ├─ 商品 → 商品搜索/详情
     └─ 投诉 → 人工工单
 → 回复生成（LLM + 引用）
 → 输出校验（敏感词/长度/转人工标记）
 → 结束
```

## 2. 节点配置

### 开始节点

变量：

```json
{
  "user_id": "string",
  "session_id": "string",
  "message": "string"
}
```

### 意图分类

Prompt：

```text
你是电商客服意图分类器。只输出 JSON：
{"intent":"product|order|logistics|after_sales|coupon|complaint|faq|unknown",
 "department":"美妆|服饰|鞋|箱包|食品饮料|母婴|家居日用|null",
 "audience":"老人|儿童|男士|女士|null",
 "order_id":"DDxxxxxxx|null"}
用户：{{message}}
```

### 知识库检索

- 知识库：售后政策、发货、发票、退货、过敏、孕妇、会员、支付。
- TopK：3。
- 输出：`retrieved_chunks`。
- 回复时要求引用 chunk，不确定就转人工。

### 条件分支

| 条件 | 分支 |
|---|---|
| `intent == order/logistics` | HTTP 订单/物流 |
| `intent == after_sales` | 售后条件 + HTTP 退货 |
| `intent == product` | 商品搜索/详情 |
| `intent == complaint` | 人工工单 |
| 其他 | RAG 回答 |

### HTTP 节点

订单：

```text
GET {ERP_BASE_URL}/erp/orders/{{order_id}}
Header: X-API-Key: {{erp_api_key}}
```

退货：

```text
POST {ERP_BASE_URL}/erp/returns
Header: Idempotency-Key: return-{{order_id}}-{{session_id}}
Body: {"order_id":"{{order_id}}","reason":"{{reason}}","opened":true,"quantity":1}
```

### 回复生成

System：

```text
你是小美，电商全品类导购兼售后。
事实必须来自知识库或 HTTP 结果，不要编。
顾客生气时先道歉、复述、给选项；不要辩解。
输出不超过 300 字；需要人工时输出 [转人工]。
```

### 输出校验

- 包含 `[转人工]` 时，必须有工单号。
- 不得出现“不演了/你爱买不买/这是规定”。
- 物流单号必须出现在 HTTP 结果中。
- 超过 500 字截断。

## 3. 截图清单

- 工作流全图
- 意图分类节点
- 知识库检索节点
- HTTP 订单节点
- 条件分支
- 一次完整运行结果

## 4. 面试怎么讲

> “Python 版本验证了业务规则和评测；Coze/Dify 版本把同样的节点画出来，方便运营/产品修改话术和知识库。两边共用同一套意图、知识库和 HTTP 接口，不是两套逻辑。”
