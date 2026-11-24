"""FastAPI 服务：聊天、会话、画像与健康检查。"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .agent import SessionOwnershipError, ShoppingAgent
from .config import Settings
from .guardrails import RateLimitExceeded
from .metrics import Metrics
from .storage import Store


logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    session_id: Optional[str] = Field(default=None, max_length=64)
    user_id: str = Field(default="user_001", max_length=64)


class ProfileUpdate(BaseModel):
    skin_type: Optional[str] = Field(default=None, max_length=32)
    concerns: Optional[List[str]] = None
    budget: Optional[int] = Field(default=None, ge=0, le=100000)
    allergies: Optional[List[str]] = None


SCENARIOS = [
    {"label": "给老人买防滑鞋", "message": "给家里老人买一双防滑、宽楦的健步鞋，预算300以内", "tag": "老人"},
    {"label": "给儿童买零食", "message": "给5岁孩子买点零食，要安全一点", "tag": "儿童"},
    {"label": "男士通勤衬衫", "message": "给男士买一件通勤穿的纯棉衬衫，XL", "tag": "男士"},
    {"label": "家庭饮料整箱", "message": "家里聚餐，想买一箱无糖茶饮料", "tag": "食品"},
    {"label": "油皮面霜", "message": "我是油皮，想买300以内的面霜", "tag": "美妆"},
    {"label": "态度投诉", "message": "你啥态度？我要投诉", "tag": "投诉"},
]


def create_app(settings: Optional[Settings] = None, agent: Optional[ShoppingAgent] = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        if application.state.owns_agent and application.state.agent is not None:
            application.state.agent.close()

    app = FastAPI(
        title="小美 · 全品类生活馆 Agent",
        description="意图识别、工具调用、RAG、多轮记忆、情绪兜底、售后与风控完整闭环",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.agent = agent
    app.state.owns_agent = agent is None
    app.state.metrics = Metrics()

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next: Any) -> Any:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            app.state.metrics.record(500, (time.perf_counter() - started) * 1000)
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        app.state.metrics.record(response.status_code, duration_ms)
        response.headers["X-Response-Time-Ms"] = "%.1f" % duration_ms
        return response

    def get_agent() -> ShoppingAgent:
        if app.state.agent is None:
            store = Store(str(settings.db_path))
            app.state.agent = ShoppingAgent(settings=settings, store=store)
        return app.state.agent

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc), "retry_after": exc.retry_after},
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.get("/", include_in_schema=False)
    def index() -> Any:
        path: Path = settings.web_dir / "index.html"
        if path.exists():
            return FileResponse(str(path), media_type="text/html; charset=utf-8")
        return JSONResponse({"message": "小美 Agent API 已启动，前端文件缺失", "docs": "/docs"})

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        data = get_agent().health()
        data["metrics"] = app.state.metrics.summary()
        return data

    @app.get("/api/metrics")
    def metrics() -> Dict[str, Any]:
        return {"metrics": app.state.metrics.summary()}

    @app.get("/api/scenarios")
    def scenarios() -> Dict[str, Any]:
        return {"scenarios": SCENARIOS}

    @app.post("/api/chat")
    def chat(payload: ChatRequest) -> Dict[str, Any]:
        try:
            result = get_agent().chat(
                payload.message,
                session_id=payload.session_id,
                user_id=payload.user_id,
            )
            return result.to_dict()
        except SessionOwnershipError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/sessions/{session_id}")
    def session_history(session_id: str, user_id: str = Query(default="user_001")) -> Dict[str, Any]:
        try:
            messages = get_agent().get_session_history(session_id, user_id)
            return {"session_id": session_id, "user_id": user_id, "messages": messages}
        except KeyError:
            raise HTTPException(status_code=404, detail="会话不存在")
        except SessionOwnershipError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

    @app.delete("/api/sessions/{session_id}")
    def reset_session(session_id: str, user_id: str = Query(default="user_001")) -> Dict[str, Any]:
        try:
            deleted = get_agent().reset_session(session_id, user_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="会话不存在")
            return {"ok": True, "session_id": session_id}
        except SessionOwnershipError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

    @app.get("/api/profile/{user_id}")
    def get_profile(user_id: str) -> Dict[str, Any]:
        return {"profile": get_agent().get_profile(user_id)}

    @app.patch("/api/profile/{user_id}")
    def update_profile(user_id: str, payload: ProfileUpdate) -> Dict[str, Any]:
        updates = payload.model_dump(exclude_none=True)
        try:
            profile = get_agent().update_profile(user_id, updates)
            return {"ok": True, "profile": profile}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/handoffs")
    def list_handoffs(status: str = Query(default="open"), limit: int = Query(default=20, ge=1, le=100)) -> Dict[str, Any]:
        # 演示用只读接口；生产环境应加管理员鉴权
        agent_instance = get_agent()
        return {"handoffs": agent_instance.store.list_handoffs(status=status, limit=limit)}

    return app


app = create_app()
