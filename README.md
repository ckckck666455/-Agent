# 小美 · 全品类生活馆 Agent

[![CI](https://github.com/ckckck666455/-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/ckckck666455/-Agent/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Tests](https://img.shields.io/badge/tests-55%20passed-brightgreen)
![RAG](https://img.shields.io/badge/RAG-Hit%401%20100%25-informational)

一个可以直接运行的全品类零售导购 / 售后 Agent 完整项目：美妆、服饰、鞋、箱包、食品饮料、母婴、家居日用。它不是“套壳聊天”，而是把**工具调用、RAG、多轮记忆、情绪兜底、业务风控、ERP 适配、转人工、持久化、Web 界面、测试与评测**串成了一个闭环。

- **双模式**：配置 DeepSeek Key 走真实模型；没有 Key 自动切换离线规则引擎，所有场景照样跑通。
- **事实来自工具**：库存、价格、订单、物流、优惠券、售后资格都不让模型编。
- **企业级护栏**：情绪升级、提示词注入、越权查单、重复发券、幻觉物流单号、PII 日志脱敏。
- **RAG + 评测**：TF-IDF 字符向量基线，25 条检索评测 Hit@1 100%；48 条 Agent 评测。
- **ERP/API 适配**：mock ERP/OMS + HTTP 客户端，超时/重试/幂等/降级。
- **可直接演示**：CLI 一键跑 10 个场景，FastAPI + 单页 Web 聊天界面。
- **v2 全品类**：35 款商品，支持老人 / 儿童 / 男士 / 女士 / 家庭采购；新增品类路由、人群适配和服务补救。
- **可继续改**：数据、工具、Prompt、UI、存储层都做了拆分。

> 演示数据均为虚构，不产生真实交易；护肤建议不构成医疗诊断。  
> 数据与隐私说明见 [NOTICE.md](NOTICE.md)、[docs/data-privacy.md](docs/data-privacy.md)；API Key 不会进入仓库。

---

## 1. 功能地图

| 模块 | 能力 |
|---|---|
| 售前导购 | 按部门 / 品类 / 人群 / 规格 / 预算查真实商品，最多推荐 3 款，说明价格、库存、适用理由和注意事项 |
| 商品对比 | 2-3 款商品的价格、适用人群、规格/成分、库存对比，并结合用户画像给结论 |
| 人群适配 | 老人防滑/高钙、儿童安全/年龄、男士/女士场景化、家庭组合采购 |
| 服务补救 | 顾客发火/质疑态度时先道歉、复述、给选项；拦截“不演了/你爱买不买”等防御性话术 |
| 订单物流 | 按订单号查状态、商品、金额、承运商、运单号、物流轨迹；校验订单归属 |
| 售后退货 | 校验签收时间、是否拆封、退货原因；过敏/质量问题走特殊通道，生成售后单 |
| 优惠券 | 挽单券上限 20 元、同一用户限一张；活动券、会员权益单独查询 |
| 会员与活动 | 等级、积分、升级条件、满减、赠品、会员日 |
| 政策知识库 | 25 条 FAQ，TF-IDF 字符向量 RAG，25 条检索评测 Hit@1 100% |
| 运营分析 | 选品（销量/退货率/库存周转/毛利）、营销（核销/收入/成本/ROI） |
| 情绪识别 | 关键词 + 强度 + 否定 + 连续负面升级；愤怒/投诉/监管威胁直接转人工，不消耗模型调用 |
| 多轮记忆 | 用户画像长期保存 + 会话摘要 + 最近消息窗口 + token 预算裁剪 |
| 转人工 | 情绪兜底、用户主动要求、模型承诺转人工时自动建工单，工单幂等 |
| 安全护栏 | 提示词注入拦截、PII 脱敏、参数白名单、工具调用次数/重复调用限制、物流单号幻觉拦截 |
| 双模式 | DeepSeek 工具调用 + 离线规则引擎；DeepSeek 失败自动降级，不中断演示 |
| 可观测 | SQLite 审计日志、工具 trace、意图/情绪/模式/延迟、`/api/metrics`（P50/P95/P99） |

---

## 2. 快速开始

要求：**Python 3.8+**。

```bash
cd xiaomei-shop-agent

python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

# 可选：复制环境变量模板；不填 Key 也能运行
# Windows
copy .env.example .env
# macOS / Linux
cp .env.example .env
```

### 2.1 一键演示（推荐先跑这个）

```bash
python run_cli.py --demo
```

会依次演示：

1. 全品类目录 → 给老人选防滑鞋
2. 给 5 岁孩子选零食，先看安全
3. 给男士选通勤纯棉衬衫（带尺码）
4. 美妆多轮：面霜 → 油皮 → 嫌贵发券
5. 订单物流：真实运单号与轨迹
6. 过敏售后：已拆封仍走质量问题通道
7. 商品对比：价格、人群、规格
8. 情绪与补救：“你啥态度” → 先接住，再处理投诉
9. 提示词注入：拒绝越权
10. 发券风控：同一用户第二张被拒

> 演示模式使用独立的 `runtime/demo.db`，每次启动会重建，不会污染交互数据。

### 2.2 交互式 CLI

```bash
python run_cli.py
```

常用命令：

```text
/help     查看帮助
/reset    清空当前会话记忆
/profile  查看用户画像
/demo     提示独立演示命令
/quit     退出
```

单轮调用：

```bash
python run_cli.py -m "我是油皮，想买300以内的面霜"
python run_cli.py -m "给老人买一双防滑鞋，预算300以内" --user user_004
python run_cli.py -m "给5岁孩子买点零食" --user user_005
python run_cli.py -m "帮我查订单 DD2026001 到哪了" --user user_001
```

### 2.3 Web 版

```bash
python run_api.py --port 8000
```

打开 <http://127.0.0.1:8000>，API 文档在 <http://127.0.0.1:8000/docs>。

页面包含：对话区、快捷问题、模式徽标、工具调用 chip、情绪标签、转人工工单卡片、清空会话。桌面和移动端都适配。

### 2.4 接入 DeepSeek

编辑 `.env`：

```dotenv
LLM_MODE=auto
DEEPSEEK_API_KEY=sk-你的真实Key
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_FALLBACK_MODEL=deepseek-chat
```

- `LLM_MODE=auto`：有 Key 用 DeepSeek，没有 Key 自动离线。
- `LLM_MODE=offline`：强制离线，便于测试和面试演示。
- `LLM_MODE=deepseek`：强制真实模型，缺少 Key 会直接报错。
- 如果主模型名不可用，会自动尝试 fallback 模型；仍失败则降级到离线引擎，保证对话不中断。

---

## 3. 实际效果示例

### 全品类：先看有什么

```text
客户 > 你们卖什么
小美 > 我们目前有 7 个部门：
       美妆、服饰、鞋、箱包、食品饮料、母婴、家居日用。
       您想买什么、给谁买、预算多少？我直接帮您筛。

客户 > 给老人买一双防滑鞋，预算300以内
小美 > 300 元以内适合老人穿的防滑鞋，目前有一款很合适：
       老人防滑健步鞋，259 元，库存 36 双。
       防滑橡胶大底、宽楦不挤脚，36-44 码。
       请问您穿多大码？我帮您确认库存。
```

### 儿童零食：安全边界

```text
客户 > 给5岁孩子买点零食，要安全一点
小美 > 优先看成分简单、独立包装、过敏风险低的：
       儿童奶酪棒 49.9 元，适合 3 岁以上，含乳制品，乳蛋白过敏不能吃；
       每日坚果 99 元，原味独立装，但坚果是过敏原，5 岁吃需要大人看着。
       孩子对牛奶或坚果过敏吗？我按这个帮您定。
```

### 售前多轮（美妆）

```text
客户 > 你好，我想买个面霜
小美 > 按您的条件，我筛出这几款：
       1. 修护保湿面霜 ¥399（库存30）——保湿、修护。
       2. 清润控油面霜 ¥299（库存50）——控油、毛孔。
       您更看重哪一点？我可以帮您缩小到一款。

客户 > 我是油皮，T区特别油
小美 > 我找到一款比较匹配的：
       1. 清润控油面霜 ¥299（库存50）——适合油皮。
       您更看重哪一点？我可以帮您缩小到一款。

客户 > 有点贵啊，能便宜点吗
小美 > 已为您申请到 20 元优惠券（券码 XM...，有效期至 2026-11-11），
       全场正价商品可用，单笔限用一张。下单时会自动抵扣。
```

### 订单物流

```text
客户 > 帮我查一下订单 DD2026001 到哪了
小美 > 订单 DD2026001 当前「已发货」，商品：清润控油面霜×1，实付 ¥299。
       承运商：顺丰速运，运单号：SF123456789，预计 2026-11-05 送达。
       最新：2026-11-03 08:15 快递员正在派送，请保持电话畅通。
```

### 情绪与补救

```text
客户 > 你啥态度
小美 > 抱歉，刚才我的表达让您不舒服了，是我没处理好。
       您具体遇到的是哪件事：查订单/物流、退货换货、还是投诉转人工？
       您告诉我先办哪一件，我按您说的做。

客户 > 你们这什么垃圾服务，我要投诉
小美 > 很抱歉让您有不好的体验。我先停止推荐，已为您转接人工客服，
       工单 H2026...，人工会尽快接入处理。[转人工]
```

“你啥态度”先降级、给选项；“投诉/12315”再转人工。不会和顾客争辩，也不会说“不演了/你爱买不买”。

---

## 4. 架构

```text
                    ┌──────────────────────────────┐
                    │        CLI / Web / API        │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │  ShoppingAgent 编排层         │
                    │  限流 → 输入清洗 → 情绪分流    │
                    │  → NLU/画像 → 记忆 → LLM 循环  │
                    │  → 输出护栏 → 持久化           │
                    └───────┬──────────────┬────────┘
                            │              │
              ┌─────────────▼────┐  ┌──────▼─────────────┐
              │ DeepSeekLLM      │  │ MockLLM             │
              │ 工具调用 + 重试   │  │ 离线意图规划 + 工具  │
              │ 失败自动降级      │  │ 结果组织            │
              └─────────────┬────┘  └──────┬─────────────┘
                            └──────┬───────┘
                                   │ tool_calls
                    ┌──────────────▼───────────────┐
                    │ CommerceToolkit（20 个工具）   │
                    │ 商品/库存/订单/物流/售后/券/   │
                    │ 会员/活动/FAQ/购物车/转人工    │
                    └───────┬──────────────┬────────┘
                            │              │
                 ┌──────────▼────┐  ┌──────▼──────────┐
                 │ SQLite Store   │  │ JSON 业务数据    │
                 │ 会话/画像/券/  │  │ 商品/订单/FAQ/   │
                 │ 售后/工单/审计 │  │ 用户/活动        │
                 └───────────────┘  └─────────────────┘
```

### 一次对话的完整链路

```text
用户消息
  → 限流 + 输入清洗
  → 情绪检测
       ├─ 高危：直接建单转人工，不调模型
       └─ 正常：继续
  → 意图识别 + 实体抽取 + 画像更新
  → 提示词注入检测
       ├─ 命中：安全拒绝
       └─ 正常：继续
  → 知识库预检索（仅作参考）
  → 组装 system + 用户画像 + 会话摘要 + 最近历史
  → LLM 工具循环（最多 4 轮 / 6 次工具）
       ├─ 模型返回 tool_calls
       ├─ 服务端注入 user_id，执行工具
       ├─ 工具结果回填为 role=tool
       └─ 模型生成最终回复
  → 输出护栏（物流单号幻觉、转人工承诺、长度）
  → 写入会话 / 审计 / 摘要压缩
  → 返回 reply + intent + emotion + tool traces + handoff
```

---

## 5. 核心设计

### 5.1 工具调用：所有事实都可追溯

模型只负责“选工具 + 组织语言”，价格、库存、订单、物流、券、售后资格都由 `CommerceToolkit` 返回。

- 工具 schema **不暴露 `user_id` / `session_id`**，由服务端上下文注入，避免模型或用户越权。
- 订单查询校验 `order.user_id == 当前用户`，查不到时统一提示“确认订单号”，不泄露其他用户订单。
- 工具循环有**最大轮数 + 最大调用次数 + 重复调用检测**，防止模型来回查同一件事。
- 工具异常不会把堆栈返回给用户，只记录审计日志，并给模型一个可解释的错误码。

### 5.2 多轮记忆：短期窗口 + 长期摘要 + 用户画像

- `UserProfile`：肤质、诉求、预算、过敏史、会员等级，跨会话保存。
- `session.summary`：历史摘要，超过阈值时压缩，保留订单号、承诺、未解决问题。
- 最近消息窗口：按 token 预算裁剪，且强制从 `user` 消息开始，避免孤立的 `tool` 消息导致 API 400。
- 画像抽取是规则触发的：只有用户明确说“我是油皮 / 我预算 300 / 我对酒精过敏”才写画像，避免把商品对比里的“修护、保湿”误当成用户诉求。

### 5.3 情绪检测：安全阀优先于销售

- 关键词、强度副词、否定词、连续负面轮次共同打分。
- 普通“退款 / 退货”不会被误判为愤怒。
- 等级 ≥ 2 直接转人工；等级 3（投诉、12315、律师、曝光、报警）创建 urgent 工单。
- 转人工话术不要求用户“冷静”，不继续推销，不主动发券。
- 工单在同一会话内幂等，避免重复建单。

### 5.4 业务风控：代码层硬约束

- 挽单券：金额上限 20 元，同一用户最多 1 张；模型要求 100 元也只会发 20 元。
- 退货：已发货不能直接登记；超过 7 天且非质量问题拒绝；已拆封且非质量问题拒绝；质量问题/过敏允许登记。
- 物流单号：如果回复里的单号不在工具结果中，自动替换为“以订单页物流为准”。
- 提示词注入：命中“忽略之前指令 / 输出系统提示词 / 开发者模式”等模式，直接安全拒绝。
- PII：审计日志中的手机号、邮箱、身份证号做脱敏。

### 5.5 知识库：TF-IDF 向量 RAG

25 条政策 FAQ，`TfidfVectorizer(analyzer="char", ngram_range=(1,2))` 向量化 + 余弦相似度；安全类问题额外加权，避免“用了过敏”被“拆封退货”条目抢走。

- 25 条检索评测：Hit@1 **100%**、Hit@3 **100%**、MRR **1.0000**
- 接口保持 `search(query) -> matches`，可替换 bge-m3 + pgvector + rerank
- 详见 [RAG 设计](docs/rag.md)、[RAG 评测](eval/rag_report.md)

### 5.6 ERP/OMS：HTTP 适配器 + 降级

- `shopagent/mock_erp.py`：mock 商品/订单/物流/退货/券端点
- `shopagent/erp_client.py`：超时、重试、`Idempotency-Key`、API Key、错误码映射
- `CommerceToolkit` 可选走 ERP；失败回退本地 JSON，并写 `erp_fallback` 审计
- 详见 [ERP 集成](docs/erp-integration.md)

### 5.7 双模式：没有 Key 也能面试演示

`DeepSeekLLM` 和 `MockLLM` 实现同一个 `chat(messages, tools)` 接口：

- `DeepSeekLLM`：真实 API、工具调用、模型回退、重试。
- `MockLLM`：规则规划器，第一轮生成 `tool_calls`，第二轮读取 `role=tool` 结果组织回复。
- `ResilientLLM`：DeepSeek 失败时自动降级到 Mock，保证演示不中断。

因此，**离线模式不是写死台词**：它仍然走意图识别 → 工具调用 → 结果组织 → 输出护栏的完整链路。

---

## 6. 工具清单

| 工具 | 作用 |
|---|---|
| `list_categories` | 列出 7 个部门与细分类目，回答“你们卖什么” |
| `search_products` | 按部门、品类、人群、规格、关键词、预算查商品 |
| `get_product_detail` | 商品规格、材质/成分、用法、注意事项、库存 |
| `check_stock` | 真实库存与购买数量校验 |
| `compare_products` | 2-3 款商品对比 |
| `query_order` | 订单状态、商品、金额、物流、售后状态 |
| `list_orders` | 当前用户最近订单 |
| `query_logistics` | 承运商、运单号、轨迹、异常 |
| `create_return_request` | 退货/退款/换货登记与资格校验 |
| `issue_coupon` | 挽单券，金额上限 + 防重复 |
| `list_coupons` | 当前用户优惠券 |
| `get_member_benefits` | 会员等级、积分、权益、升级条件 |
| `get_promotions` | 进行中的活动、满减、赠品 |
| `product_insights` | 选品/运营：销量、退货率、库存周转、毛利 |
| `campaign_insights` | 营销：核销、收入、成本、ROI |
| `search_faq` | 政策知识库 RAG 检索 |
| `recommend_routine` | 早晚护肤流程与商品组合 |
| `add_to_cart` | 加入购物车并计算小计 |
| `view_cart` | 查看购物车 |
| `update_user_profile` | 更新长期画像 |
| `get_user_profile` | 查询画像 |
| `request_human_handoff` | 创建人工工单 |

---

## 7. API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/` | Web 聊天界面 |
| `GET` | `/api/health` | 模式、模型、商品/FAQ 数量、统计 |
| `GET` | `/api/scenarios` | 快捷问题 |
| `POST` | `/api/chat` | 单轮对话 |
| `GET` | `/api/sessions/{id}?user_id=` | 会话历史 |
| `DELETE` | `/api/sessions/{id}?user_id=` | 清空会话 |
| `GET` | `/api/profile/{user_id}` | 用户画像 |
| `PATCH` | `/api/profile/{user_id}` | 更新画像 |
| `GET` | `/api/handoffs?status=open` | 工单列表（演示用，生产需鉴权） |

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "我是油皮，想买300以内的面霜",
    "session_id": "demo-session",
    "user_id": "user_001"
  }'
```

响应包含：

```json
{
  "reply": "……",
  "session_id": "demo-session",
  "intent": {"intent": "pre_sales", "entities": {}},
  "emotion": {"level": 0, "label": "平静", "score": 0.0},
  "tool_calls": [{"name": "search_products", "ok": true, "summary": "……"}],
  "handoff": null,
  "sources": [],
  "usage": {},
  "mode": "offline",
  "latency_ms": 12.3
}
```

---

## 8. 项目结构

```text
xiaomei-shop-agent/
├── run_cli.py                  # CLI 入口
├── run_api.py                  # FastAPI 入口
├── run_erp.py                  # mock ERP/OMS 入口
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── pytest.ini
├── .github/workflows/ci.yml    # compile + pytest + eval
├── data/
│   ├── products.json           # 35 款全品类商品 + 销量/退货率/毛利
│   ├── orders.json             # 12 个订单 + 物流轨迹
│   ├── users.json              # 7 个演示账号与画像
│   ├── faqs.json               # 25 条政策 FAQ
│   └── promotions.json         # 5 个活动 + 核销/ROI
├── shopagent/
│   ├── agent.py                # 编排层：护栏、情绪、记忆、工具循环
│   ├── llm.py                  # DeepSeek 客户端 + 自动降级
│   ├── mock_llm.py             # 离线规则引擎（同接口）
│   ├── tools.py                # 20 个业务工具 + 参数白名单
│   ├── erp_client.py           # ERP HTTP：超时/重试/幂等/鉴权
│   ├── mock_erp.py             # mock ERP/OMS 服务
│   ├── metrics.py              # 请求数/错误率/P95
│   ├── nlu.py                  # 意图/实体/画像抽取
│   ├── emotion.py              # 情绪打分与升级
│   ├── memory.py               # 画像上下文、窗口裁剪、摘要压缩
│   ├── knowledge.py            # TF-IDF 向量 RAG
│   ├── guardrails.py           # 限流、PII、回复裁剪、幻觉/语气拦截
│   ├── prompts.py              # 系统提示词
│   ├── storage.py              # SQLite 持久化
│   ├── schemas.py              # 数据结构
│   ├── config.py               # 环境变量配置
│   ├── api.py                  # FastAPI + /api/metrics
│   ├── cli.py                  # 终端交互
│   └── web/index.html          # 单页聊天界面
├── tests/                      # 55 个测试
├── eval/                       # 48 条 Agent 评测 + 25 条 RAG 评测
│   ├── cases.json
│   ├── run_eval.py
│   ├── rag_eval.py
│   ├── report.md
│   └── rag_report.md
├── loadtest/locustfile.py      # Locust 压测
├── docs/
│   ├── jd-mapping.md           # 岗位逐条对照
│   ├── portfolio.md            # 一页作品集
│   ├── demo-script.md          # 5 分钟演示
│   ├── resume-bullets.md       # 三版简历 bullet
│   ├── rag.md                  # RAG 设计
│   ├── erp-integration.md      # ERP 集成
│   ├── stability.md            # 部署/压测/监控
│   ├── langgraph-migration.md  # LangGraph 迁移图
│   ├── adr/                    # 3 个架构决策记录
│   ├── architecture.md         # 更详细的设计说明
│   └── interview.md            # 面试讲解与演示脚本
└── runtime/                    # SQLite / 日志（运行时生成）
```

---

## 9. 测试与评测

### 9.1 单元/集成测试

```bash
python -m pytest tests -q
```

覆盖：

- 意图识别、实体抽取、画像触发条件
- 情绪等级、否定、连续负面升级
- 商品筛选、订单归属、退货窗口、拆封规则、券上限/防重复、购物车、FAQ
- Agent 多轮记忆、订单查询、愤怒转人工、注入拦截、售后、医疗安全
- 会话窗口裁剪、摘要压缩
- FastAPI 聊天、历史、权限、清空、画像

当前结果：**55 passed**。

### 9.2 Agent 评测

```bash
python eval/run_eval.py
```

评测集 48 条，覆盖品类目录、老人/儿童/男士/女士、美妆、订单物流、售后、优惠券、情绪、注入、未知问题、多轮记忆。输出：

- 任务通过率
- 工具命中率
- 转人工 precision / recall
- 防御性话术数量
- 分类通过率与失败用例

当前离线结果：

```text
通过：48/48（100.0%）
工具命中：100.0%
转人工 precision/recall：100.0% / 100.0%
防御性话术：0 处
```

> 这是**规则化离线回归基线**，不是人工语义评分；100% 只代表当前用例集的关键事实、工具和边界都满足，不代表真实用户 100% 满意。线上可跑 `python eval/run_eval.py --online`（会产生 API 费用）。

详细报告见 [eval/report.md](eval/report.md)。

### 9.3 RAG 检索评测

```bash
python eval/rag_eval.py
```

25 条 FAQ 查询，输出 Hit@1、Hit@3、MRR：

```text
backend: tfidf-char-vector
Hit@1: 100.0%  Hit@3: 100.0%  MRR: 1.0000
```

详细报告见 [eval/rag_report.md](eval/rag_report.md)。

### 9.4 ERP/API 测试

```bash
python -m pytest tests/test_erp_client.py -q
```

覆盖 5xx 重试、`Idempotency-Key`、订单/物流、退货幂等。

### 9.5 压测

```bash
pip install locust
locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 1m --host http://127.0.0.1:8000
```

也可以不用 Locust：

```bash
python loadtest/run_load.py --url http://127.0.0.1:8010 --requests 500 --concurrency 50
```

实测（离线 MockLLM，50 并发，500 请求）：

```text
RPS 90.76｜平均 530.6ms｜P95 735.0ms｜P99 827.7ms｜错误率 0%
```

指标看 `/api/metrics`：请求数、错误率、P50/P95/P99。报告见 [loadtest/report.md](loadtest/report.md)。

> 这是离线规则引擎 + 本地 SQLite 的压测，不代表 DeepSeek 线上延迟。

> 如果你所在环境的 `pytest-cov` 版本过旧（例如 2.x）与 pytest 8 冲突，出现 `ValueError: 'int' is not callable`，可以执行：
>
> ```bash
> python -m pytest tests -q -p no:cov
> ```
>
> 或者升级 `pytest-cov`。这不是项目代码问题。

---

## 10. 演示账号与数据

| 用户 | 画像 | 订单 |
|---|---|---|
| `demo_user` | 新用户，无画像 | 无；用于演示画像逐步建立 |
| `user_001` | 职场女性，油皮，关注控油/痘痘/毛孔，预算 300，黄金会员 | DD2026001 已发货、DD2026002 待发货、DD2026005 过期订单、DD2026008 待发货、DD2026009 已签收 |
| `user_002` | 干皮男士，关注保湿/泛红/屏障，对酒精过敏，预算 400 | DD2026003 已签收、DD2026006 已取消 |
| `user_003` | 抗老需求，混合肌，关注抗老/暗沉，预算 800，铂金会员 | DD2026004 运输中、DD2026007 已签收 |
| `user_004` | 张爷爷，老年顾客，关注防滑/高钙/易消化，预算 300 | DD2026010 已签收（老人健步鞋） |
| `user_005` | 李女士，宝妈/家庭采购，预算 500 | DD2026011 已签收（儿童奶酪棒） |
| `user_006` | 王先生，通勤男士，预算 600 | DD2026012 已发货（男士纯棉衬衫） |

重点订单：

- `DD2026001`：已发货，顺丰 `SF123456789`，可演示物流。
- `DD2026002`：待发货，可演示取消/改地址。
- `DD2026005`：签收超过 7 天，演示退货窗口拒绝。
- `DD2026009`：签收 2 天、已拆封、过敏，演示质量问题售后通道。
- `DD2026010`：老人健步鞋，演示鞋类退换。
- `DD2026011`：儿童奶酪棒，演示食品类售后边界。
- `DD2026012`：男士衬衫，演示服饰尺码/物流。

`DEMO_NOW` 默认 `2026-11-04 14:00`，用于让退货窗口判断稳定。换数据时记得同步修改。

---

## 11. 如何改成你自己的项目

1. **换数据**：改 `data/*.json`，保持字段结构即可。
2. **换工具**：在 `shopagent/tools.py` 里实现方法，并注册到 `TOOL_SCHEMAS`。参数会自动经过白名单清洗。
3. **换人设/规则**：改 `shopagent/prompts.py` 的 `BASE_SYSTEM_PROMPT`。
4. **换模型**：改 `.env` 的 `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL`；只要兼容 OpenAI Chat Completions + tool calls 即可。
5. **换存储**：`ShopAgent` 依赖 `Store` 的少量方法，替换成 PostgreSQL/Redis 时实现同名接口即可。
6. **换前端**：`shopagent/web/index.html` 是纯静态单页，直接改 CSS/JS。
7. **加评估**：建议记录 `intent`、`tool_calls`、`handoff`、用户反馈，离线跑回归集。

---

## 12. 上线前还需要什么

这是**可运行、可演示、可测试的原型**，不是直接可上线的生产系统。生产化建议：

- **鉴权**：目前 `user_id` 由客户端传入，生产必须从登录态/网关解析，禁止客户端伪造。
- **真实业务系统**：接商品中心、OMS、WMS、支付、售后、优惠券平台；所有写操作加幂等键和事务。
- **数据库**：SQLite 换 PostgreSQL；会话/审计可加 Redis 缓存和 TTL。
- **可观测**：接入 OpenTelemetry、Prometheus、结构化日志、工单告警；记录 token 成本与工具失败率。
- **评测**：建立 200+ 条真实语料回归集，指标包括任务完成率、工具参数准确率、幻觉率、转人工准确率/召回率、平均轮次、P95 延迟、单次成本。
- **合规**：隐私政策、用户授权、敏感信息加密、未成年人保护、广告法/化妆品宣称审核。
- **体验**：流式输出、打字机效果、人工坐席实时接管、消息重试、附件/图片识别。
- **风控**：Prompt 注入检测升级为模型 + 规则双层；工具调用加权限矩阵和审计告警。

---

## 13. 面试怎么讲（3 分钟版）

> 我做了一个全品类生活馆导购 Agent，目标不是“让模型会聊天”，而是让它在真实业务里**不编造、能办事、可兜底**。  
>   
> 第一层是工具调用：商品、库存、订单、物流、售后、优惠券、选品/营销分析都封装成工具，模型只做意图判断和话术组织。工具 schema 不暴露 user_id，身份由服务端注入，订单查询会校验归属，避免越权。  
>   
> 第二层是记忆与 RAG：用户画像跨会话保存，会话内有摘要压缩和 token 窗口裁剪；FAQ 用 TF-IDF 字符向量做 RAG 基线，25 条检索评测 Hit@1 100%，可换 dense embedding + rerank。  
>   
> 第三层是风控和兜底：愤怒/投诉/12315 在调模型之前就被情绪规则拦截，直接建高优先级工单，不推销、不发券；挽单券金额上限 20 元且同一用户只能一张；退货会校验签收时间、拆封状态和原因；如果模型编了不在工具结果里的物流单号，输出护栏会替换掉；顾客质疑态度时，输出层会拦截“不演了/你爱买不买”等防御性话术。  
>   
> 系统集成层写了 mock ERP/OMS 的 HTTP 客户端，带超时、重试、幂等键、鉴权和降级；工程侧有 55 个测试、48 条 Agent 评测、25 条 RAG 评测、Docker/CI/Locust 和 `/api/metrics`。  
>   
> 没有 Key 也能用离线引擎完整演示；DeepSeek 失败会自动降级，不会中断。下一步是用 LangGraph 把编排改成显式状态图，再补真实 ERP 沙箱和 50 并发压测报告。

更完整的自我介绍、追问 Q&A、7 分钟演示脚本见 [docs/interview.md](docs/interview.md)。  
岗位对照、作品集、演示脚本、简历 bullet 见 [docs/jd-mapping.md](docs/jd-mapping.md)、[docs/portfolio.md](docs/portfolio.md)、[docs/demo-script.md](docs/demo-script.md)、[docs/resume-bullets.md](docs/resume-bullets.md)。

---

## 14. 常见问题

**Q：没有 DeepSeek Key 能运行吗？**  
能。`LLM_MODE=auto` 且 Key 为空时自动使用离线规则引擎，`python run_cli.py --demo` 可直接跑完 10 个场景。

**Q：`deepseek-flash` 不存在怎么办？**  
会尝试 `DEEPSEEK_FALLBACK_MODEL=deepseek-chat`；仍失败则降级到离线引擎。你也可以在 `.env` 里直接改成账号可用的模型名。

**Q：为什么演示里的退货日期是 2026 年？**  
数据是虚构的，`DEMO_NOW` 固定了演示时间锚点。换真实数据时删掉 `DEMO_NOW` 或改成当前日期即可。

**Q：Windows 终端中文/¥ 乱码？**  
项目已尝试 `sys.stdout.reconfigure(encoding="utf-8")`；仍乱码时执行：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```

**Q：测试报 `'int' is not callable`？**  
旧版 `pytest-cov` 与 pytest 8 冲突，执行 `python -m pytest tests -q -p no:cov`，或升级 `pytest-cov`。

**Q：能直接商用到生产吗？**  
不能。它是作品集/原型级项目，鉴权、真实交易、合规、评测、可观测都需要补齐，详见第 12 节。

---

## 15. 开源与发布

- GitHub 仓库：https://github.com/ckckck666455/-Agent
- 协议：[MIT License](LICENSE)
- 数据与商标说明：[NOTICE.md](NOTICE.md)
- 数据与隐私：[docs/data-privacy.md](docs/data-privacy.md)
- 贡献：[CONTRIBUTING.md](CONTRIBUTING.md)
- 安全：[SECURITY.md](SECURITY.md)
- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 变更记录：[CHANGELOG.md](CHANGELOG.md)
- Release notes：[RELEASE_NOTES.md](RELEASE_NOTES.md)
- 发布到 GitHub 的步骤：[docs/publishing.md](docs/publishing.md)

发布前请确认：

- `.env`、`runtime/*.db`、`.idea/` 没有被提交
- `data/` 里没有真实用户/订单/手机号
- README 的截图/指标是真实跑出来的
- `python -m pytest tests -q`、`eval/run_eval.py`、`eval/rag_eval.py` 全绿

---

## 16. 文档与展示材料

- [岗位逐条对照](docs/jd-mapping.md)
- [一页作品集](docs/portfolio.md)
- [5 分钟演示脚本](docs/demo-script.md)
- [三版简历 bullet](docs/resume-bullets.md)
- [RAG 设计与检索评测](docs/rag.md)
- [ERP/OMS 集成](docs/erp-integration.md)
- [部署、压测与稳定性](docs/stability.md)
- [LangGraph 迁移图](docs/langgraph-migration.md)
- [Coze/Dify 工作流设计](docs/coze-workflow.md)
- [架构决策记录 ADR](docs/adr/001-orchestration.md)
- [架构与设计决策](docs/architecture.md)
- [面试讲解](docs/interview.md)
- [Agent 评测报告](eval/report.md)
- [RAG 检索报告](eval/rag_report.md)
- [压测报告](loadtest/report.md)

如果这个项目对你有帮助，建议先跑 `python run_cli.py --demo` 看完整闭环，再按第 11 节替换成自己的业务数据。
