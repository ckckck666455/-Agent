# v2.0.0 — 全品类生活馆 Agent

这是一个可直接运行、可评测、可降级的电商 AI Agent 示例。

## Highlights

- **20 个业务工具**：商品、订单、物流、售后、券、会员、活动、FAQ、购物车、转人工、选品/营销分析。
- **35 SKU / 7 部门**：美妆、服饰、鞋、箱包、食品饮料、母婴、家居日用。
- **RAG**：TF-IDF 字符向量基线，25 条检索评测 Hit@1 100%、MRR 1.0000。
- **ERP 适配**：mock ERP/OMS + HTTP 客户端，超时/重试/幂等/鉴权/降级。
- **情绪补救**：态度不满先道歉/复述/给选项；投诉/12315 再转人工；拦截防御性话术。
- **评测**：55 个测试；48/48 Agent 评测；工具命中 100%；转人工 precision/recall 100%。
- **压测**：离线 50 并发 / 500 请求，P95 735ms，错误率 0%。
- **工程**：Dockerfile、docker-compose、GitHub Actions、Locust、`/api/metrics`。

## Quickstart

```bash
git clone https://github.com/<your-name>/xiaomei-shop-agent.git
cd xiaomei-shop-agent
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env       # 可选；不填 Key 也能离线运行
python run_cli.py --demo --offline
```

Web：

```bash
python run_api.py --port 8000 --offline
# http://127.0.0.1:8000
```

## Known limitations

- LangGraph 迁移图已提供，但当前 Python 3.8 环境未安装 LangGraph。
- RAG 是 TF-IDF 基线，不是 dense embedding + rerank。
- ERP 是 mock，不是真实 ERP/OMS。
- 1 年经验/真实生产流量不在本项目范围内。

## License

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE.md).
