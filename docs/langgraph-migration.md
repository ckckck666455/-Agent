# LangGraph 迁移方案

## 1. 为什么当前不是 LangGraph

项目运行在 **Python 3.8**，`langgraph` 当前没有可安装的 3.8 发行版（`pip index versions langgraph` 无匹配）。  
所以先用自研循环把业务跑通；下面给出 1:1 的 LangGraph 迁移图，切到 Python 3.10 环境即可落地。

不要简历写“精通 LangGraph”，除非你真的把图跑起来。正确写法：

> “先用自研编排跑通业务，正在用 LangGraph 重构为显式状态图。”

## 2. 状态

```python
class AgentState(TypedDict):
    messages: list
    user_id: str
    session_id: str
    intent: str
    emotion: dict
    retrieved: list
    tool_calls: list
    tool_results: list
    reply: str
    handoff: dict | None
    rounds: int
```

## 3. 图

```python
from langgraph.graph import StateGraph, END

builder = StateGraph(AgentState)
builder.add_node("guard_input", guard_input)
builder.add_node("detect_emotion", detect_emotion)
builder.add_node("classify", classify)
builder.add_node("retrieve", retrieve)
builder.add_node("plan", plan)
builder.add_node("execute_tools", execute_tools)
builder.add_node("reflect", reflect)
builder.add_node("respond", respond)
builder.add_node("handoff", handoff)
builder.add_node("finish", finish)

builder.set_entry_point("guard_input")
builder.add_edge("guard_input", "detect_emotion")
builder.add_conditional_edges(
    "detect_emotion",
    lambda s: "handoff" if s["emotion"]["should_handoff"] else "classify",
    {"handoff": "handoff", "classify": "classify"},
)
builder.add_edge("classify", "retrieve")
builder.add_edge("retrieve", "plan")
builder.add_edge("plan", "execute_tools")
builder.add_edge("execute_tools", "reflect")
builder.add_conditional_edges(
    "reflect",
    lambda s: "plan" if s["needs_more_tools"] and s["rounds"] < 4 else "respond",
    {"plan": "plan", "respond": "respond"},
)
builder.add_edge("respond", "finish")
builder.add_edge("handoff", "finish")
builder.add_edge("finish", END)

graph = builder.compile(checkpointer=checkpointer)
```

## 4. 节点对应现有代码

| LangGraph 节点 | 现有方法 |
|---|---|
| `guard_input` | `ShoppingAgent.chat` 的 sanitize / rate limit / injection |
| `detect_emotion` | `EmotionDetector.analyze` |
| `classify` | `NLU.classify` |
| `retrieve` | `KnowledgeBase.search` |
| `plan` | 目前由 LLM tool_calls 隐式完成 |
| `execute_tools` | `CommerceToolkit.execute` |
| `reflect` | 目前由工具循环下一轮隐式完成 |
| `respond` | `ShoppingAgent._postprocess` + `_finish` |
| `handoff` | `ShoppingAgent._ensure_handoff` |

## 5. 迁移步骤

1. 新建 Python 3.10 环境：`pip install langgraph`。
2. 把 `ShoppingAgent.chat` 拆成节点函数，状态放 `AgentState`。
3. 用 `SqliteSaver` / Postgres checkpointer 存状态，支持人工中断/恢复。
4. 用 `interrupt_before=["execute_tools"]` 做售后/高金额人工审批。
5. 保留现有工具层、输出护栏、评测集；图只替换编排，不重写业务规则。
6. 用同一套 `eval/run_eval.py` 对比迁移前后通过率。

## 6. 面试怎么讲

> “我没有在 Python 3.8 上硬装 LangGraph，而是先用自研循环把业务跑通，再把节点、状态、checkpoint、人工中断一一映射到 LangGraph。迁移时工具层和评测集不变，这样可以对比迁移前后通过率，而不是为了框架重写业务。”
