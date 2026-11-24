# Contributing

感谢你愿意改进小美 Agent。这个项目是**可运行的电商 Agent 示例**，不是生产系统；提交时请优先保证“可复现、可测试、可解释”。

## 1. 本地开发

```bash
git clone https://github.com/<your-name>/xiaomei-shop-agent.git
cd xiaomei-shop-agent
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

没有 Key 也能运行：

```bash
python run_cli.py --demo --offline
```

## 2. 提交前必须跑

```bash
python -m compileall -q shopagent
python -m pytest tests -q
python eval/run_eval.py
python eval/rag_eval.py
```

如果改了前端或 API，请补一条手动验证说明。

## 3. 新增工具的要求

1. 在 `shopagent/tools.py` 实现方法。
2. 注册到 `TOOL_SCHEMAS`，写清楚“什么时候用/不要什么时候用”。
3. 参数必须经过 `clean_arguments` 白名单。
4. 业务规则（金额、权限、状态）必须在代码层，不靠 Prompt。
5. 至少补 1 个测试；改核心路径要补 eval case。
6. 不要在工具里打印/存储 API Key、手机号、地址。

## 4. 改 Prompt 的要求

- 不要只写“更友好”；写清楚触发条件、禁止话术、输出格式。
- 改 Prompt 后跑 `eval/run_eval.py`，确认没有把旧场景改坏。
- 情绪/转人工相关改动，必须说明 precision/recall 的变化。

## 5. 数据与隐私

- 不要提交真实用户订单、手机号、地址、聊天记录。
- 演示数据必须虚构；新增数据请脱敏。
- `.env`、`runtime/*.db`、`*.log` 不应提交。
- 不要提交他人的 API Key、Cookie、Token。

## 6. PR 约定

- 一个 PR 只做一件事；标题写清楚 `feat/fix/docs/test/chore`。
- 描述里写：改了什么、为什么、怎么验证、有什么风险。
- UI 改动附截图；API 改动附 curl/响应。
- 不接受的 PR：只加商品数量、只改文案不跑测试、引入不必要的大依赖。

## 7. 提交信息

```text
feat: add ERP idempotency adapter
fix: block defensive replies after attitude complaint
docs: add JD mapping and demo script
test: cover child toothpaste detail routing
```

## 8. 开源协议

提交即同意以 [MIT License](LICENSE) 发布。
