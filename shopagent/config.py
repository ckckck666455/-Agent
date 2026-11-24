"""项目级配置：全部通过环境变量覆盖，代码里不写死密钥。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 读取，避免为一个演示项目额外依赖 python-dotenv。"""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    """运行配置。

    LLM_MODE:
      - auto     有 DEEPSEEK_API_KEY 时走真实模型，否则离线规则引擎
      - deepseek 强制真实模型（缺少 Key 直接报错）
      - offline  强制离线演示，方便无网络/无 Key 运行测试
    """

    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    runtime_dir: Path = PROJECT_ROOT / "runtime"
    web_dir: Path = PROJECT_ROOT / "shopagent" / "web"
    db_path: Path = PROJECT_ROOT / "runtime" / "shop_agent.db"
    api_key: Optional[str] = None
    base_url: str = "https://api.deepseek.com"
    erp_base_url: Optional[str] = None
    erp_api_key: Optional[str] = None
    model: str = "deepseek-flash"
    fallback_model: Optional[str] = "deepseek-chat"
    llm_mode: str = "auto"
    offline: bool = False
    temperature: float = 0.4
    max_tokens: int = 700
    request_timeout: float = 50.0
    max_tool_rounds: int = 4
    max_tool_calls: int = 6
    max_reply_chars: int = 480
    history_token_budget: int = 3000
    max_recent_messages: int = 24
    summary_trigger_tokens: int = 3800
    summary_keep_messages: int = 8
    coupon_max_amount: int = 20
    retention_coupon_limit: int = 1
    return_window_days: int = 7
    rate_limit_per_minute: int = 40
    demo_now: Optional[str] = None
    log_level: str = "INFO"
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, project_root: Optional[Path] = None) -> "Settings":
        root = Path(project_root) if project_root else PROJECT_ROOT
        _load_dotenv(root / ".env")

        mode = os.environ.get("LLM_MODE", "auto").strip().lower()
        if mode not in {"auto", "deepseek", "offline"}:
            mode = "auto"
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or None
        if mode == "deepseek" and not api_key:
            raise RuntimeError(
                "LLM_MODE=deepseek 但未设置 DEEPSEEK_API_KEY。"
                "请配置 .env，或改用 LLM_MODE=offline。"
            )

        runtime_dir = Path(os.environ.get("SHOP_AGENT_RUNTIME", str(root / "runtime")))
        data_dir = Path(os.environ.get("SHOP_AGENT_DATA", str(root / "data")))
        settings = cls(
            project_root=root,
            data_dir=data_dir,
            runtime_dir=runtime_dir,
            web_dir=root / "shopagent" / "web",
            db_path=runtime_dir / "shop_agent.db",
            api_key=api_key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            erp_base_url=os.environ.get("ERP_BASE_URL", "").strip() or None,
            erp_api_key=os.environ.get("ERP_API_KEY", "").strip() or None,
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-flash").strip(),
            fallback_model=os.environ.get("DEEPSEEK_FALLBACK_MODEL", "deepseek-chat").strip() or None,
            llm_mode=mode,
            temperature=_env_float("LLM_TEMPERATURE", 0.4),
            max_tokens=_env_int("LLM_MAX_TOKENS", 700),
            request_timeout=_env_float("LLM_TIMEOUT", 50.0),
            max_tool_rounds=_env_int("MAX_TOOL_ROUNDS", 4),
            max_tool_calls=_env_int("MAX_TOOL_CALLS", 6),
            max_reply_chars=_env_int("MAX_REPLY_CHARS", 480),
            history_token_budget=_env_int("HISTORY_TOKEN_BUDGET", 3000),
            max_recent_messages=_env_int("MAX_RECENT_MESSAGES", 24),
            summary_trigger_tokens=_env_int("SUMMARY_TRIGGER_TOKENS", 3800),
            summary_keep_messages=_env_int("SUMMARY_KEEP_MESSAGES", 8),
            coupon_max_amount=_env_int("COUPON_MAX_AMOUNT", 20),
            retention_coupon_limit=_env_int("RETENTION_COUPON_LIMIT", 1),
            return_window_days=_env_int("RETURN_WINDOW_DAYS", 7),
            rate_limit_per_minute=_env_int("RATE_LIMIT_PER_MINUTE", 40),
            demo_now=os.environ.get("DEMO_NOW", "").strip() or None,
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )
        settings.offline = mode == "offline" or (mode == "auto" and not api_key)
        settings.ensure_dirs()
        return settings

    def ensure_dirs(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
