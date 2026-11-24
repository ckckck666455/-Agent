# ERP/OMS/API 集成说明

## 1. 为什么做这一层

JD 要求“工具调用、API 对接（商品/订单/物流/ERP）”。  
只读本地 JSON 不能证明系统集成能力，所以加了：

- mock ERP/OMS 服务
- HTTP 客户端：超时、重试、幂等键、鉴权、错误映射
- 工具层可选走 ERP，失败回退本地数据

## 2. 架构

```text
Agent Tool
  → CommerceToolkit
      ├─ ERP_BASE_URL 配置存在 → HttpCommerceClient
      │     ├─ GET  /erp/orders/{id}
      │     ├─ GET  /erp/orders/{id}/logistics
      │     ├─ POST /erp/returns
      │     └─ POST /erp/coupons
      └─ 失败/未配置 → 本地 JSON/SQLite（离线演示）
```

## 3. 关键点

### 超时与重试

- 默认 5s 超时。
- 5xx / 网络异常重试 2 次，指数退避。
- 4xx（401/403/404）不重试，直接映射为业务错误。

### 幂等

- 退货/发券带 `Idempotency-Key`。
- mock ERP 缓存 key → response，重复请求返回同一结果。
- 生产要落库唯一索引，不能只靠内存。

### 鉴权

- `X-API-Key`（demo）。
- 生产换 OAuth2 / 签名 / mTLS，按 ERP 提供方要求。

### 降级

- ERP 不可用时，工具记录 `erp_fallback` 审计，回退本地数据。
- 回复里不暴露“ERP 挂了”，只说“当前查询可能不是最新”，必要时转人工。

## 4. 运行

```bash
# 终端 1：mock ERP
python run_erp.py --port 8100

# 终端 2：Agent 连接 ERP
$env:ERP_BASE_URL="http://127.0.0.1:8100"
python run_api.py --port 8000 --offline
```

测试：

```bash
python -m pytest tests/test_erp_client.py -q
```

覆盖：

- 5xx 重试
- `Idempotency-Key` 透传
- 订单/物流查询
- 退货重复提交幂等

## 5. 实测

- `GET /erp/health` → 35 products / 12 orders
- Agent 查询 `DD2026001` → trace 显示“ERP 实时”，返回顺丰 `SF123456789`
- Agent 登记 `DD2026009` 退货 → `return_id` 由 ERP 生成，trace 显示“ERP 已受理”
- ERP 不可用时自动回退本地 JSON，并写 `erp_fallback` 审计

## 6. 生产化还缺什么

- 真实 ERP/OMS 沙箱与字段映射
- 对账任务：订单/退款/库存三方一致
- 补偿任务：超时未决、重复退款、库存占用
- 全链路 trace id
- 限流/熔断/隔离舱
- 审计与权限矩阵

## 7. 面试怎么讲

> “我没有真实 ERP 权限，所以写了 mock ERP 和 HTTP 客户端，把超时、重试、幂等、鉴权和降级都跑通；工具层可切换本地/远程。生产替换 base_url 和字段映射即可，但还需要对账、补偿和全链路 trace。”
