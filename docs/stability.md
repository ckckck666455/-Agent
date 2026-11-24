# 稳定性、部署与压测

## 1. 已有

- `Dockerfile` / `docker-compose.yml`：agent + mock ERP 一键启动。
- GitHub Actions：compile + pytest + Agent eval + RAG eval。
- Locust 脚本：`loadtest/locustfile.py`。
- `/api/health`：模式、商品数、FAQ 数、统计。
- `/api/metrics`：请求数、错误率、平均/P50/P95/P99 延迟。
- 降级：DeepSeek 失败 → 离线规则引擎；ERP 失败 → 本地数据 + 审计。
- 超时/重试：LLM 50s；ERP 5s + 2 次重试；工具调用轮数/次数上限。

## 2. 启动

```bash
docker compose up --build
```

- Agent：`http://127.0.0.1:8000`
- Mock ERP：`http://127.0.0.1:8100/erp/health`

没有 Docker 时：

```bash
python run_erp.py --port 8100
$env:ERP_BASE_URL="http://127.0.0.1:8100"
python run_api.py --port 8000 --offline
```

## 3. 压测

```bash
pip install locust
locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 1m --host http://127.0.0.1:8000
```

也可以不用 Locust，直接跑：

```bash
python loadtest/run_load.py --url http://127.0.0.1:8010 --requests 500 --concurrency 50
```

看：

- RPS
- P50/P95/P99
- 错误率
- 降级次数
- 平均回复长度

> 压测请用 `--offline`，否则会消耗 DeepSeek token。线上压测要单独的测试 key/额度。

### 实测结果（离线 MockLLM，50 并发，500 请求）

| 指标 | 结果 |
|---|---:|
| RPS | 90.76 |
| 平均延迟 | 530.6 ms |
| P50 | 520.1 ms |
| P95 | 735.0 ms |
| P99 | 827.7 ms |
| 错误率 | 0% |

> 这是离线规则引擎 + 本地 SQLite 的压测，反映编排/HTTP/DB 开销，不代表 DeepSeek 线上延迟。报告见 `loadtest/report.md`。

## 4. 生产化检查清单

- [ ] 鉴权从登录态解析 user_id，禁止客户端伪造
- [ ] Redis 限流/缓存，Postgres 持久化
- [ ] 工具调用全链路 trace id
- [ ] LLM/ERP 超时、熔断、隔离
- [ ] 退款/优惠券幂等唯一索引
- [ ] 工单 SLA 与人工接管
- [ ] 日志脱敏、审计保留期
- [ ] Prompt/模型/工具版本管理
- [ ] 离线回归集 + 线上抽样评测
- [ ] 成本看板：token、图片/视频/语音、单次会话成本

## 5. 常见故障

| 故障 | 表现 | 处理 |
|---|---|---|
| DeepSeek 401 | 启动/首轮失败 | 检查 `.env`，降级离线 |
| DeepSeek 402 | 余额不足 | 充值或切离线 |
| 模型名 404 | `deepseek-flash` 不可用 | `DEEPSEEK_MODEL=deepseek-chat` |
| 端口 8000 占用 | `Errno 10048` | 停旧进程或换端口 |
| ERP 超时 | 工具回退本地 | 查 `erp_fallback` 审计 |
| 工具死循环 | 轮数到上限 | 检查重复调用/参数 |
| 防御性话术 | 输出护栏命中 | 看 `tone_guard` 审计，改 Prompt |

## 6. 面试怎么讲

> “我把稳定性拆成四层：模型失败降级、ERP 失败回退、工具调用预算、输出护栏。部署用 Docker Compose，CI 跑测试+评测，压测用 Locust，指标从 `/api/metrics` 看。现在缺的是真实 50 并发报告和 Redis/Postgres 生产化。”
