# 发布到 GitHub

本机目前没有 `gh` CLI，也还没有初始化 git；按下面步骤可以在 10 分钟内发布。

## 1. 创建远程仓库

在 GitHub 网页：

```text
New repository
Name: xiaomei-shop-agent
Visibility: Public
Initialize: 不要勾选 README / .gitignore / license（本地已有）
```

或者安装 `gh` 后：

```bash
gh repo create xiaomei-shop-agent --public --source=. --remote=origin --push
```

## 2. 本地提交

```bash
cd xiaomei-shop-agent
git init -b main
git add .
git status --short
```

**提交前必须确认**：`git status` 里没有 `.env`、`runtime/*.db`、`.idea/`。

```bash
git commit -m "feat: initial open-source release of Xiaomei retail agent"
git tag v2.0.0
```

如果 git 没配置身份：

```bash
git config user.name "你的名字"
git config user.email "你的GitHub邮箱"
```

## 3. 推送

```bash
git remote add origin https://github.com/<your-name>/xiaomei-shop-agent.git
git push -u origin main
git push origin v2.0.0
```

如果使用 SSH：

```bash
git remote add origin git@github.com:<your-name>/xiaomei-shop-agent.git
```

## 4. 仓库设置

### Description

```text
A runnable e-commerce AI agent with tool calls, RAG, ERP adapter, emotion handling and evaluation.
```

中文版：

```text
可运行的电商全品类 AI 智能体：工具调用、RAG、ERP 适配、情绪补救、48 条评测。
```

### Topics

```text
ai-agent, llm, rag, ecommerce, customer-service, deepseek, fastapi, langgraph, tool-calling, evaluation
```

### 功能开关

- Issues：开
- Discussions：可选
- Actions：开（CI 已在 `.github/workflows/ci.yml`）
- Security → Private vulnerability reporting：开

## 5. Release

把 `CHANGELOG.md` 的 v2.0.0 粘到 Release notes，附：

- 30 秒 GIF / 3 分钟视频
- 架构图截图
- 评测结果：55 tests、48/48、RAG 25/25、P95 735ms
- 已知限制：LangGraph 迁移中、RAG 是 TF-IDF 基线、ERP 是 mock

## 6. 截图/视频建议

1. Web 聊天：老人防滑鞋、儿童零食、订单售后、态度投诉。
2. 评测报告：`eval/report.md` 截图。
3. 压测报告：`loadtest/report.md` 截图。
4. 架构图：README 里的 ASCII 图或重画。
5. 3 分钟视频：问题 → 演示 → 架构 → 指标 → 取舍。

## 7. 发布前安全检查

```bash
git status --short
git check-ignore -v .env
git grep -n "sk-" -- . ':!*.md' ':!data/*'
git grep -n "DEEPSEEK_API_KEY=" -- . ':!*.md' ':!*.example'
```

确认：

- `.env` 被忽略
- 没有 `sk-` 真实 Key
- 没有真实手机号/地址/订单
- `runtime` 数据库未提交
- `.idea` 未提交

## 8. 发布后

- 把 README 的 `OWNER/REPO` 占位符替换成你的仓库地址（`SECURITY.md`、Issue config）。
- 在 README 顶部加 CI badge：

```markdown
[![CI](https://github.com/<your-name>/xiaomei-shop-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-name>/xiaomei-shop-agent/actions/workflows/ci.yml)
```

- 把仓库链接放到简历/作品集。
- 打 tag 后不要 force push；后续用 PR 流程。
