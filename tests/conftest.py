import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shopagent.agent import ShoppingAgent
from shopagent.config import Settings
from shopagent.storage import Store


@pytest.fixture()
def settings():
    # 不使用 pytest 的 tmp_path：部分 Windows 沙箱会给 pytest 创建的临时目录
    # 打上受限 ACL，导致后续 resolve 失败。这里由项目自己在 runtime 下创建。
    run_dir = ROOT / "runtime" / "test_dbs" / ("case_" + uuid.uuid4().hex)
    run_dir.mkdir(parents=True, exist_ok=True)
    base = Settings.from_env()
    base.runtime_dir = run_dir
    base.db_path = run_dir / "test.db"
    base.data_dir = ROOT / "data"
    base.web_dir = ROOT / "shopagent" / "web"
    base.offline = True
    base.api_key = None
    base.demo_now = "2026-11-04 14:00"
    base.rate_limit_per_minute = 200
    base.max_tool_rounds = 4
    return base


@pytest.fixture()
def agent(settings):
    store = Store(str(settings.db_path))
    instance = ShoppingAgent(settings=settings, store=store)
    yield instance
    instance.close()


@pytest.fixture()
def toolkit(agent):
    return agent.toolkit


@pytest.fixture()
def ctx():
    from shopagent.tools import ToolContext

    def make(user_id="user_001", **kwargs):
        return ToolContext(user_id=user_id, session_id="test-session", profile={}, **kwargs)

    return make
