"""VetLink AI — 稽核紀錄儲存 (提案 §7.1 稽核與回溯引擎).

以 stdlib sqlite3 實作，無額外相依。保存輸入、規則、版本、回答及影響關係，
供回答護照回查與 Impact Replay 影響查找使用。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..models import AnswerPassport

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "audit.db"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
    audit_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL,
    role TEXT NOT NULL,
    refusal_reason TEXT NOT NULL,
    request_json TEXT NOT NULL,
    passport_json TEXT NOT NULL,
    response_json TEXT,
    fingerprint TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    rules_bundle_version TEXT
);

CREATE TABLE IF NOT EXISTS citations (
    audit_id TEXT NOT NULL,
    passage_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    PRIMARY KEY (audit_id, passage_id, claim_id)
);
CREATE INDEX IF NOT EXISTS idx_citations_passage ON citations(passage_id);
CREATE INDEX IF NOT EXISTS idx_citations_doc ON citations(doc_id);

CREATE TABLE IF NOT EXISTS impact_events (
    event_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    old_version TEXT,
    new_version TEXT,
    risk_tier TEXT NOT NULL,
    affected_audit_id TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    notified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_impact_audit ON impact_events(affected_audit_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditStore:
    """SQLite 稽核紀錄。thread-safe (每次操作各自建立連線)。"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            self._shared: Optional[sqlite3.Connection] = None
        else:
            # in-memory 需維持單一連線
            self._shared = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._shared is not None:
            return self._shared
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        with self._lock:
            conn.executescript(SCHEMA)
            conn.commit()
        if self._shared is None:
            conn.close()

    # ------------------------------------------------------------------
    def record_answer(
        self,
        passport: AnswerPassport,
        request_payload: Dict[str, Any],
        response_payload: Optional[Dict[str, Any]] = None,
        fingerprint: str = "",
    ) -> str:
        from ..engine.passport import passport_fingerprint

        fp = fingerprint or passport_fingerprint(passport)
        conn = self._connect()
        with self._lock:
            conn.execute(
                """INSERT OR REPLACE INTO answers
                   (audit_id, created_at, state, role, refusal_reason, request_json,
                    passport_json, response_json, fingerprint, status, rules_bundle_version)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    passport.audit_id,
                    passport.created_at,
                    passport.answer_state.value,
                    passport.applicable_role.value,
                    passport.refusal_reason.value,
                    json.dumps(request_payload, ensure_ascii=False, default=str),
                    passport.model_dump_json(),
                    json.dumps(response_payload or {}, ensure_ascii=False, default=str),
                    fp,
                    "active",
                    passport.rules_bundle_version,
                ),
            )
            conn.execute("DELETE FROM citations WHERE audit_id = ?", (passport.audit_id,))
            for b in passport.claim_bindings:
                for p in b.passages:
                    conn.execute(
                        """INSERT OR REPLACE INTO citations
                           (audit_id, passage_id, doc_id, version, claim_id)
                           VALUES (?,?,?,?,?)""",
                        (passport.audit_id, p.passage_id, p.doc_id, p.version, b.claim_id),
                    )
            conn.commit()
        if self._shared is None:
            conn.close()
        return passport.audit_id

    def get_passport(self, audit_id: str) -> Optional[AnswerPassport]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT passport_json FROM answers WHERE audit_id = ?", (audit_id,)
        ).fetchone()
        if self._shared is None:
            conn.close()
        if not row:
            return None
        return AnswerPassport.model_validate_json(row[0])

    def get_answer_record(self, audit_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM answers WHERE audit_id = ?", (audit_id,)).fetchone()
        if self._shared is None:
            conn.close()
        return dict(row) if row else None

    def find_answers_citing_passages(self, passage_ids: List[str]) -> List[str]:
        """Impact Replay 影響查找：找出引用過指定段落的歷史回答。"""
        if not passage_ids:
            return []
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in passage_ids)
        rows = conn.execute(
            f"""SELECT DISTINCT c.audit_id FROM citations c
                JOIN answers a ON a.audit_id = c.audit_id
                WHERE c.passage_id IN ({placeholders}) AND a.status != 'invalidated'
                ORDER BY c.audit_id""",
            passage_ids,
        ).fetchall()
        if self._shared is None:
            conn.close()
        return [r[0] for r in rows]

    def find_answers_citing_doc(self, doc_id: str, version: Optional[str] = None) -> List[str]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        if version:
            rows = conn.execute(
                """SELECT DISTINCT audit_id FROM citations
                   WHERE doc_id = ? AND version = ? ORDER BY audit_id""",
                (doc_id, version),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT audit_id FROM citations WHERE doc_id = ? ORDER BY audit_id",
                (doc_id,),
            ).fetchall()
        if self._shared is None:
            conn.close()
        return [r[0] for r in rows]

    def set_status(self, audit_id: str, status: str) -> None:
        conn = self._connect()
        with self._lock:
            conn.execute("UPDATE answers SET status = ? WHERE audit_id = ?", (status, audit_id))
            conn.commit()
        if self._shared is None:
            conn.close()

    def record_impact_event(
        self,
        event_id: str,
        doc_id: str,
        old_version: Optional[str],
        new_version: Optional[str],
        risk_tier: str,
        affected_audit_id: str,
        action: str,
        detail: str = "",
        notified: bool = True,
    ) -> None:
        conn = self._connect()
        with self._lock:
            conn.execute(
                """INSERT OR REPLACE INTO impact_events
                   (event_id, created_at, doc_id, old_version, new_version, risk_tier,
                    affected_audit_id, action, detail, notified)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id, _now(), doc_id, old_version, new_version, risk_tier,
                    affected_audit_id, action, detail, int(notified),
                ),
            )
            conn.commit()
        if self._shared is None:
            conn.close()

    def list_impact_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM impact_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        if self._shared is None:
            conn.close()
        return [dict(r) for r in rows]

    def list_answers(self, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT audit_id, created_at, state, role, refusal_reason, status
               FROM answers ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        if self._shared is None:
            conn.close()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
        by_state = {
            r[0]: r[1]
            for r in conn.execute("SELECT state, COUNT(*) FROM answers GROUP BY state").fetchall()
        }
        invalidated = conn.execute(
            "SELECT COUNT(*) FROM answers WHERE status = 'invalidated'"
        ).fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM impact_events").fetchone()[0]
        if self._shared is None:
            conn.close()
        return {
            "total_answers": total,
            "by_state": by_state,
            "invalidated": invalidated,
            "impact_events": events,
        }


_STORE: Optional[AuditStore] = None


def get_store(db_path: Optional[str] = None) -> AuditStore:
    global _STORE
    if _STORE is None or db_path is not None:
        _STORE = AuditStore(db_path or DEFAULT_DB_PATH)
    return _STORE
