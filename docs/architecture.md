# 架构与设计决策

## 1. 目标与非目标

### 目标

1. 在电商售前/售后场景里，用真实业务数据完成任务，而不是“陪聊”。
2. 没有 API Key 也能完整演示，降低面试/评审的复现成本。
3. 把“不能编、不能越权、不能刺激用户”做成代码层约束，而不是只写在 Prompt 里。
4. 结构清晰，能替换数据、工具、模型和存储。

### 非目标

- 不是可直接上线的生产系统：没有登录态、真实支付/OMS、人工坐席实时接管。
- 不做医疗诊断：涉及皮肤疾病只给停用/就医建议。
- 不做多租户和复杂权限：演示版只有一个进程内服务。

---

## 2. 组件职责

| 组件 | 职责 | 关键文件 |
|---|---|---|
| `ShoppingAgent` | 编排一次对话的全部步骤 | `agent.py` |
| `DeepSeekLLM` | 真实模型调用、工具 schema、重试、模型回退 | `llm.py` |
| `MockLLM` | 离线意图规划、工具调用、结果组织 | `mock_llm.py` |
| `ResilientLLM` | DeepSeek 失败时自动降级 | `llm.py` |
| `CommerceToolkit` | 20 个业务工具、参数白名单、订单归属、券/退货规则 | `tools.py` |
| `NLU` | 意图、实体、画像抽取、提示词注入识别 | `nlu.py` |
| `EmotionDetector` | 情绪打分与转人工级别 | `emotion.py` |
| `MemoryManager` | 画像上下文、消息窗口、摘要压缩 | `memory.py` |
| `KnowledgeBase` | FAQ 字符 n-gram + IDF 检索 | `knowledge.py` |
| `Store` | SQLite 会话/画像/券/售后/工单/购物车/审计 | `storage.py` |
| `guardrails` | 限流、PII、回复裁剪、幻觉单号拦截 | `guardrails.py` |
| `api` / `cli` / `web` | 三种交互入口 | `api.py` / `cli.py` / `web/index.html` |

---

## 3. 一次请求的时序

```text
Client
  │ POST /api/chat {message, session_id, user_id}
  ▼
FastAPI
  ▼
ShoppingAgent.chat
  ├─ sanitize_input / RateLimiter.check
  ├─ Store.get_or_create_session（校验 session 归属）
  ├─ CommerceToolkit.get_profile（静态用户 + 动态画像）
  ├─ NLU.classify（意图/实体）
  ├─ EmotionDetector.analyze（含连续负面轮次）
  ├─ 画像更新（仅在用户明确自述时）
  ├─ 写 user 消息 + 审计
  │
  ├─ [高情绪] → Store.create_handoff → 固定话术 → _finish
  ├─ [明确转人工] → Store.create_handoff → 固定话术 → _finish
  ├─ [提示词注入] → 安全拒绝 → _finish
  │
  ├─ KnowledgeBase.search（FAQ 预检索）
  ├─ build_system_prompt（画像 + 摘要 + 情绪 + FAQ）
  ├─ MemoryManager.select_history（token/消息窗口）
  │
  ├─ for round in 1..max_tool_rounds:
  │     LLM.chat(messages, tools)
  │       ├─ 无 tool_calls → final_text
  │       └─ 有 tool_calls → 校验/去重/限额 → CommerceToolkit.execute
  │                         → 回填 role=tool → 继续
  │
  ├─ _postprocess
  │     ├─ sanitize_reply_claims（物流单号必须在工具结果里）
  │     ├─ 如果回复承诺转人工但没建单 → 补建工单
  │     ├─ 情绪 1 级补共情
  │     └─ truncate_reply
  │
  └─ _finish
        ├─ 追加 assistant 消息
        ├─ 更新 turns / negative_turns / last_intent / handoff
        ├─ MemoryManager.compact（超阈值才压缩）
        ├─ Store.save_session
        ├─ 审计
        └─ 返回 ChatResult
```

---

## 4. 数据模型

### SQLite 表

| 表 | 关键字段 | 说明 |
|---|---|---|
| `sessions` | session_id, user_id, summary, state_json, history_json | 会话、摘要、历史、轮次状态 |
| `profiles` | user_id, profile_json | 长期画像 |
| `coupons` | coupon_id, user_id, code, amount, coupon_type, status, expires_at | 挽单券风控 |
| `handoffs` | ticket_id, session_id, user_id, reason, priority, status, context_json | 人工工单 |
| `returns` | return_id, order_id, user_id, reason, refund_amount, status | 售后单 |
| `cart_items` | user_id, product_id, quantity | 购物车 |
| `audit_events` | event_type, user_id, session_id, payload_json | 审计与失败分析 |

### JSON 业务数据

- `products.json`：35 款全品类商品，含部门、品类、人群、规格、库存、注意事项、别名。
- `orders.json`：12 个订单，含状态机、物流轨迹、签收时间、售后窗口。
- `users.json`：7 个演示账号，覆盖老人、宝妈、男士、女士等画像。
- `faqs.json`：25 条政策知识。
- `promotions.json`：5 个活动。

---

## 5. 工具循环的失败语义

| 场景 | 处理 |
|---|---|
| 工具名不存在 | 返回 `UNKNOWN_TOOL`，模型可改用其他工具 |
| 参数 JSON 非法 | 当前实现回退为空参数，工具返回业务错误；审计记录原始参数 |
| 重复调用同一工具+参数 | `DUPLICATE_TOOL_CALL`，不重复执行 |
| 超过总调用次数 | `TOOL_BUDGET_EXCEEDED`，要求模型基于已有信息回答 |
| 工具内部异常 | `TOOL_ERROR`，不暴露堆栈，记录审计 |
| 模型循环 4 轮仍无回复 | 用最后一个成功工具结果兜底，避免空回复 |
| DeepSeek 不可用 | `ResilientLLM` 降级到 MockLLM，继续同一套工具链 |

---

## 6. 记忆策略

### 6.1 用户画像

只从明确自述中抽取：

- “我是油皮 / 我皮肤干 / 我 T 区特别油”
- “预算 300 / 300 以内 / 不超过 300”
- “我对酒精过敏 / 我对香精过敏”
- “怀孕 / 哺乳”

**不抽取**：

- 商品对比里的“修护、保湿”
- “用了过敏”里的“用了”
- 商品价格里的数字

### 6.2 会话窗口

- 系统提示词 + `summary` + 最近消息。
- 只保留从 `user` 开始的一段，避免 `role=tool` 成为第一条导致 OpenAI API 400。
- 旧工具结果压缩到 600 字符。
- 按估算 token 数裁剪，默认预算 3000。

### 6.3 摘要压缩

- 触发条件：历史 token > 3800 且消息数 > 8。
- 保留最近 8 条；更早的交给摘要器。
- 有真实模型时用 LLM 摘要；离线时用规则摘要（肤质、预算、订单号、近期诉求）。
- 摘要上限 800 字符。

---

## 7. 情绪分级

| 级别 | 分数 | 例子 | 行为 |
|---|---|---|---|
| 0 平静 | < 2 | “我要退款”“查订单” | 正常处理 |
| 1 不满 | 2–4.5 | “等了好几天还没发货，很失望” | 共情、停止推销、给具体动作；连续负面会升级 |
| 2 愤怒 | >= 4.5 | “我要投诉”“什么垃圾服务” | 转人工，high |
| 3 危机 | >= 7 或监管/法律威胁 | “12315 / 消协 / 律师 / 曝光 / 报警” | 转人工，urgent |

否定词会降低权重（“我不是投诉”），普通退款/退货不会误判。

---

## 8. 关键取舍

### 为什么规则 + LLM，而不是全交给 LLM？

- 情绪、注入、券上限、订单归属、退货窗口属于**硬约束**，规则可解释、可测试、零 token 成本。
- 开放表达、商品推荐话术、多轮组织交给 LLM。
- 离线模式用规则引擎替代 LLM，但工具和护栏不变，保证行为一致。

### 为什么用 SQLite？

- 单文件、零外部服务、可直接运行。
- 会话、画像、券、工单、审计都需要事务和查询，JSON 文件不够。
- 生产替换 PostgreSQL 时，`Store` 的方法签名可以保持。

### 为什么不直接上向量库？

- 25 条 FAQ 的规模，字符 n-gram + IDF 足够稳定，启动零依赖。
- `KnowledgeBase.search` 是抽象点，后续可替换 embedding + pgvector。

### 为什么工具 schema 不暴露 user_id？

- 防止模型被用户话术诱导查别人订单。
- 用户身份由服务端会话/登录态注入，是权限边界，不是模型参数。

---

## 9. 扩展点

| 需求 | 改哪里 |
|---|---|
| 新增商品/订单字段 | `data/*.json` + `tools.py` 的 `_product_view` / `query_order` |
| 新增工具 | `tools.py` 实现方法 + `TOOL_SCHEMAS` 注册 |
| 新增政策 | `data/faqs.json` |
| 换 Prompt | `prompts.py` |
| 换模型 | `.env` 的 model/base_url |
| 换存储 | 实现 `Store` 同名方法 |
| 换前端 | `shopagent/web/index.html` |
| 加流式 | FastAPI SSE + LLM stream + 前端逐字渲染 |
| 加人工坐席 | 工单表加坐席分配、WebSocket 接管、消息双向同步 |

---

## 10. 已知限制

1. `user_id` 由客户端传入，生产必须从登录态解析。
2. 订单/商品/券数据是本地 JSON + SQLite 模拟，未接真实业务系统。
3. 单进程限流和 SQLite 不适合多实例高并发。
4. 离线规则引擎覆盖常见场景，但不具备真实 LLM 的开放语言理解。
5. 无流式输出、无图片/语音、无多语言。
6. 无真实人工坐席，工单只落库。
7. 评测集只有单元/集成测试，缺少大规模真实语料回归。
