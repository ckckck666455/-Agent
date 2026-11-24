# 岗位对照：电商 AI 智能体搭建（Agent）

> 目标岗位：电商 AI 智能体（客服 / 售后 / 选品 / 营销 / 运营）架构与搭建。  
> 用途：面试前自查、简历改写、作品集讲解。  
> 原则：只写项目里真实做过的东西；没用过的框架不写成“精通”。

## 1. 逐条对照

| JD 要求 | 项目里的证据 | 差距 | 下一步 |
|---|---|---|---|
| 电商 AI 智能体架构设计 | `shopagent/agent.py`：限流 → 输入清洗 → 情绪分流 → NLU/画像 → 记忆 → 工具循环 → 输出护栏 → 持久化 | 目前是单 Agent + 工具循环，不是显式图 | 用 LangGraph/状态机拆成 intent→retrieve→plan→tools→reflect→respond |
| LangChain / LangGraph / Coze | 自研编排 + DeepSeek Tool Calls | 缺框架关键词与图编排 | 用 Python 3.10 环境写 LangGraph 版本；Coze/Dify 搭一个可视化工作流 |
| RAG 知识库 | `shopagent/knowledge.py`：TF-IDF 字符向量检索；`eval/rag_eval.py`：25 条查询，Hit@1 100% | 还是 TF-IDF 基线，不是 dense embedding + rerank | 接 bge-m3 / text-embedding-3-small + pgvector/FAISS，加引用和 retrieval 评测 |
| 工具调用 | 20 个工具：商品、订单、物流、售后、券、会员、活动、FAQ、购物车、转人工、选品/营销分析 | 工具以本地 JSON/SQLite 为主 | 已加 mock ERP HTTP 客户端，下一步把更多工具切到 API |
| API 对接（商品/订单/物流/ERP） | `shopagent/erp_client.py` + `shopagent/mock_erp.py`：超时、重试、幂等键、鉴权、错误映射；`tests/test_erp_client.py` | 目前是 mock ERP，不是真实 ERP/OMS | 用真实开放平台/沙箱替换 base_url，补对账与补偿 |
| 意图理解 → 规划 → 执行 → 反馈 | 意图识别、工具循环、记忆、情绪反馈 | 规划/反思不是显式节点 | 加 Planner、Reflector、Human Review；失败重规划 |
| 调试 / 压测 / 部署 / 稳定性 | 55 个 pytest；Dockerfile、docker-compose、GitHub Actions、Locust；离线 50 并发 P95 735ms、错误率 0%；`/api/metrics` | 缺真实 DeepSeek/生产环境压测 | 用独立测试 key 跑线上 20/50 并发，记录降级率与成本 |
| 电商客服 / 售后 / 导购 | 订单、物流、退货、券、FAQ、转人工、情绪补救 | 客服/售后强；选品/营销刚补 | 用 `product_insights` / `campaign_insights` 做两个业务 case |
| 选品 / 营销 / 运营 | 商品销量、退货率、库存周转、毛利；活动核销、ROI | 运营看板还没有 | 加一个只读 admin 页面：会话、工具失败、转人工、ROI |
| 低代码 / RPA | 无 | 缺 Coze/Dify/n8n 证据 | 用 Coze 或 Dify 搭 5-8 节点工作流，截图/录屏 |
| 1 年以上 AI 应用经验 | 项目 + 可运行 demo + 评测 | 年限可能被 HR 筛 | 不编年限；投接受 1 年以下/应届的岗位，用项目、外包、开源补证据 |

## 2. 匹配度判断

- **业务匹配**：客服、售后、导购、订单、物流、券、转人工——强。
- **工程匹配**：Python、FastAPI、SQLite、工具调用、测试、降级——中上。
- **架构匹配**：自研循环能讲清楚，但缺 LangGraph/Coze 图编排——中。
- **RAG 匹配**：有检索和评测，但 TF-IDF 不是 dense RAG——中。
- **系统集成**：有 mock ERP + HTTP 客户端 + 幂等，但缺真实 ERP——中。
- **稳定性**：有 Docker/CI/压测脚本/指标，但缺真实压测报告——中。

**结论：技术面能讲，简历关键词还差 3 个：LangGraph、dense RAG、真实 ERP/压测报告。**

## 3. 面试 90 秒版本

> 我做了一个电商全品类生活馆 Agent，覆盖客服、售后、导购、选品和营销。  
> 编排层是“输入护栏 → 情绪分流 → 意图/画像 → 记忆 → 工具循环 → 输出护栏”，工具不暴露 user_id，订单校验归属，券有金额上限和防重复，退货校验签收/拆封/原因。  
> RAG 侧我先做了 TF-IDF 字符向量基线，25 条检索评测 Hit@1 100%，下一步换 dense embedding + rerank。  
> 系统集成侧写了 mock ERP/OMS 的 HTTP 客户端，带超时、重试、幂等键和鉴权，能查订单/物流、登记退货。  
> 工程侧有 55 个测试、48 条 Agent 评测、Docker/CI/Locust 脚本和 `/api/metrics`；DeepSeek 失败会自动降级到离线引擎。  
> 我下一步会把编排迁到 LangGraph，并补真实 ERP 沙箱和 50 并发压测报告。

## 4. 可展示材料

- `README.md`：功能、架构、Quickstart、测试与评测
- `docs/portfolio.md`：一页作品集
- `docs/demo-script.md`：5 分钟演示脚本
- `docs/resume-bullets.md`：开发/产品/评测三版简历 bullet
- `docs/rag.md`：RAG 设计与检索评测
- `docs/erp-integration.md`：ERP/API 适配说明
- `docs/stability.md`：Docker/CI/压测/监控
- `docs/langgraph-migration.md`：LangGraph 迁移图
- `eval/report.md`：48 条 Agent 评测
- `eval/rag_report.md`：25 条 RAG 检索评测

## 5. 不要做的事

- 不要为了 JD 标签去学 Spark/Hadoop/Hive；这个岗位职责没真正用。
- 不要把“自研循环”包装成“精通 LangGraph”；面试官一问节点、state、checkpoint 就露馅。
- 不要只堆商品数量；35 个 SKU 够演示，缺的是集成、评测、稳定性。
- 不要编“1 年经验”；把项目、外包、开源贡献讲清楚，投匹配的岗位。
