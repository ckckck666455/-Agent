# Changelog

## v2.0.0 (2026-11-24)

### Added

- 全品类商品数据：35 SKU / 7 部门，支持老人、儿童、男士、女士、家庭。
- 20 个业务工具：商品、订单、物流、售后、券、会员、活动、FAQ、购物车、转人工、选品/营销分析。
- TF-IDF 字符向量 RAG + 25 条检索评测（Hit@1 100%，MRR 1.0000）。
- mock ERP/OMS + `HttpCommerceClient`：超时、重试、`Idempotency-Key`、鉴权、降级。
- 选品/营销分析：销量、退货率、库存周转、毛利、核销、ROI。
- `/api/metrics`：请求数、错误率、P50/P95/P99。
- Dockerfile、docker-compose、GitHub Actions、Locust/并发压测脚本。
- 48 条 Agent 评测：工具命中 100%、转人工 precision/recall 100%、防御性话术 0。
- 离线压测：50 并发 / 500 请求，P95 735ms，错误率 0%。
- 文档：JD 对照、作品集、演示脚本、简历 bullet、RAG/ERP/稳定性/LangGraph/Coze、3 个 ADR。

### Changed

- 项目定位从“美妆导购”升级为“全品类生活馆”。
- 情绪处理从“直接转人工”升级为“态度不满先补救，投诉再转人工”。
- 回复长度上限从 320 调到 480，避免对比回答被截断。

## v1.0.0 (2026-11-04)

- 初始版本：美妆导购 Agent、12 个商品、3 个工具、情绪转人工、SQLite、42 个测试。
