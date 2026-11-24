## 改了什么

<!-- 一句话说明 -->

## 为什么

<!-- 业务问题/技术问题 -->

## 怎么验证

- [ ] `python -m compileall -q shopagent`
- [ ] `python -m pytest tests -q`
- [ ] `python eval/run_eval.py`
- [ ] `python eval/rag_eval.py`
- [ ] 手动验证（截图/curl）

## 风险

<!-- 影响哪些工具/场景；是否需要迁移/回滚 -->

## 检查

- [ ] 没有提交 `.env`、API Key、真实订单/手机号/地址
- [ ] 新增工具经过参数白名单
- [ ] 业务规则在代码层，不只写在 Prompt
- [ ] 文档/README 已更新（如需要）
