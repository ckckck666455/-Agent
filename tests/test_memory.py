from shopagent.memory import MemoryManager, estimate_tokens, summarize_rule_based
from shopagent.storage import SessionRecord


def _history(turns=12):
    messages = []
    for index in range(turns):
        messages.append({"role": "user", "content": "第%d轮：我是油皮，预算300，关注控油" % index})
        messages.append({"role": "assistant", "content": "收到，第%d轮回复" % index})
    return messages


def test_select_history_starts_with_user(settings):
    memory = MemoryManager(settings)
    selected = memory.select_history(_history(20))
    assert selected
    assert selected[0]["role"] == "user"
    assert len(selected) <= settings.max_recent_messages


def test_rule_based_summary_keeps_facts():
    summary = summarize_rule_based(
        [
            {"role": "user", "content": "我是油皮，预算300，主要想控油"},
            {"role": "assistant", "content": "好的"},
        ]
    )
    assert "油皮" in summary
    assert "300" in summary
    assert "控油" in summary


def test_compact_reduces_history(settings):
    memory = MemoryManager(settings)
    settings.summary_keep_messages = 6
    session = SessionRecord(
        session_id="compact",
        user_id="user_001",
        history=_history(20),
    )
    before = len(session.history)
    changed = memory.compact(session, llm=None, force=True)
    assert changed is True
    assert len(session.history) < before
    assert session.summary
    assert session.history[0]["role"] == "user"


def test_estimate_tokens_grows_with_text():
    assert estimate_tokens("你好") > 0
    assert estimate_tokens("你好" * 10) > estimate_tokens("你好")
