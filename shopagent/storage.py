"""SQLite 持久化层：会话、用户画像、优惠券、售后单、转人工工单、购物车与审计日志。"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class SessionRecord:
    session_id: str
    user_id: str
    summary: str = ""
    state: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class Store:
    """轻量 SQLite 仓库。

    生产环境可以替换为 PostgreSQL / Redis；这里保持单文件、零外部服务，
    方便直接运行和面试演示。所有写操作都在进程内锁中完成。
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                state_json TEXT NOT NULL DEFAULT '{}',
                history_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS profiles (
                user_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS coupons (
                coupon_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                code TEXT NOT NULL UNIQUE,
                amount INTEGER NOT NULL,
                coupon_type TEXT NOT NULL DEFAULT 'retention',
                status TEXT NOT NULL DEFAULT 'active',
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS handoffs (
                ticket_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'normal',
                status TEXT NOT NULL DEFAULT 'open',
                context_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS returns (
                return_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                refund_amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending_review',
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS cart_items (
                user_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, product_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_coupons_user ON coupons(user_id, coupon_type)",
            "CREATE INDEX IF NOT EXISTS idx_handoffs_session ON handoffs(session_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_returns_order ON returns(order_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_events(session_id)",
        ]
        with self._lock, self._conn:
            for statement in statements:
                self._conn.execute(statement)

    # ------------------------------------------------------------------
    # 会话
    # ------------------------------------------------------------------
    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._row_to_session(row) if row else None

    def get_or_create_session(self, session_id: str, user_id: str) -> SessionRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row:
                return self._row_to_session(row)
            stamp = now_iso()
            record = SessionRecord(
                session_id=session_id,
                user_id=user_id,
                state={"turns": 0, "negative_turns": 0},
                history=[],
                created_at=stamp,
                updated_at=stamp,
            )
            self._conn.execute(
                "INSERT INTO sessions(session_id, user_id, summary, state_json, history_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.session_id,
                    record.user_id,
                    record.summary,
                    json.dumps(record.state, ensure_ascii=False),
                    json.dumps(record.history, ensure_ascii=False),
                    record.created_at,
                    record.updated_at,
                ),
            )
            self._conn.commit()
            return record

    def save_session(self, record: SessionRecord) -> None:
        record.updated_at = now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO sessions(session_id, user_id, summary, state_json, history_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "summary=excluded.summary, state_json=excluded.state_json, "
                "history_json=excluded.history_json, updated_at=excluded.updated_at",
                (
                    record.session_id,
                    record.user_id,
                    record.summary,
                    json.dumps(record.state, ensure_ascii=False),
                    json.dumps(record.history, ensure_ascii=False),
                    record.created_at or now_iso(),
                    record.updated_at,
                ),
            )

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def list_sessions(self, user_id: str, limit: int = 10) -> List[SessionRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [self._row_to_session(row) for row in rows]

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> SessionRecord:
        def loads(value: str, default: Any) -> Any:
            try:
                return json.loads(value) if value else default
            except (TypeError, ValueError):
                return default

        return SessionRecord(
            session_id=row["session_id"],
            user_id=row["user_id"],
            summary=row["summary"] or "",
            state=loads(row["state_json"], {}),
            history=loads(row["history_json"], []),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # 用户画像
    # ------------------------------------------------------------------
    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT profile_json FROM profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["profile_json"])
        except (TypeError, ValueError):
            return None

    def save_profile(self, user_id: str, profile: Dict[str, Any]) -> None:
        stamp = now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO profiles(user_id, profile_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at",
                (user_id, json.dumps(profile, ensure_ascii=False), stamp, stamp),
            )

    # ------------------------------------------------------------------
    # 优惠券
    # ------------------------------------------------------------------
    def count_coupons(self, user_id: str, coupon_type: str = "retention") -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM coupons WHERE user_id = ? AND coupon_type = ?",
                (user_id, coupon_type),
            ).fetchone()
        return int(row["c"] if row else 0)

    def add_coupon(
        self,
        coupon_id: str,
        user_id: str,
        code: str,
        amount: int,
        coupon_type: str,
        reason: str,
        expires_at: str,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO coupons(coupon_id, user_id, code, amount, coupon_type, status, reason, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                (coupon_id, user_id, code, amount, coupon_type, reason, now_iso(), expires_at),
            )

    def list_coupons(self, user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM coupons WHERE user_id = ?"
        params: List[Any] = [user_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # 转人工
    # ------------------------------------------------------------------
    def create_handoff(
        self,
        ticket_id: str,
        session_id: str,
        user_id: str,
        reason: str,
        priority: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        stamp = now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO handoffs(ticket_id, session_id, user_id, reason, priority, status, context_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)",
                (
                    ticket_id,
                    session_id,
                    user_id,
                    reason,
                    priority,
                    json.dumps(context, ensure_ascii=False),
                    stamp,
                    stamp,
                ),
            )
        return {
            "ticket_id": ticket_id,
            "session_id": session_id,
            "user_id": user_id,
            "reason": reason,
            "priority": priority,
            "status": "open",
            "created_at": stamp,
        }

    def get_open_handoff(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM handoffs WHERE session_id = ? AND status = 'open' "
                "ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["context"] = json.loads(data.pop("context_json", "{}"))
        except (TypeError, ValueError):
            data["context"] = {}
        return data

    def list_handoffs(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM handoffs"
        params: List[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # 售后单
    # ------------------------------------------------------------------
    def create_return(
        self,
        return_id: str,
        order_id: str,
        user_id: str,
        reason: str,
        refund_amount: float,
        detail: str,
    ) -> Dict[str, Any]:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO returns(return_id, order_id, user_id, reason, refund_amount, status, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending_review', ?, ?)",
                (return_id, order_id, user_id, reason, refund_amount, detail, now_iso()),
            )
        return {
            "return_id": return_id,
            "order_id": order_id,
            "refund_amount": refund_amount,
            "status": "pending_review",
        }

    def get_return_by_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM returns WHERE order_id = ? ORDER BY created_at DESC LIMIT 1",
                (order_id,),
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # 购物车
    # ------------------------------------------------------------------
    def add_cart_item(self, user_id: str, product_id: str, quantity: int) -> None:
        stamp = now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO cart_items(user_id, product_id, quantity, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, product_id) DO UPDATE SET "
                "quantity = cart_items.quantity + excluded.quantity, updated_at = excluded.updated_at",
                (user_id, product_id, quantity, stamp),
            )

    def get_cart(self, user_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM cart_items WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_cart(self, user_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))

    # ------------------------------------------------------------------
    # 审计日志
    # ------------------------------------------------------------------
    def log_event(
        self,
        event_type: str,
        user_id: str = "",
        session_id: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            serialized = json.dumps(payload or {}, ensure_ascii=False)[:8000]
        except (TypeError, ValueError):
            serialized = "{}"
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit_events(event_type, user_id, session_id, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (event_type, user_id, session_id, serialized, now_iso()),
            )

    def stats(self) -> Dict[str, int]:
        tables = ["sessions", "coupons", "handoffs", "returns", "audit_events"]
        result: Dict[str, int] = {}
        with self._lock:
            for table in tables:
                row = self._conn.execute("SELECT COUNT(*) AS c FROM %s" % table).fetchone()
                result[table] = int(row["c"] if row else 0)
        return result

    def close(self) -> None:
        with self._lock:
            self._conn.close()
