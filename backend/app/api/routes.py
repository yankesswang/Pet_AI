"""VetLink AI — HTTP API 路由。

端點對應提案 §十 三幕 Demo：
    第一幕 POST /api/consult            飼主端 → 紅色拒答
    第二幕 POST /api/vet/search         獸醫端 → 藍色解鎖（需身分驗證）
    第三幕 POST /api/admin/impact-replay 管理端 → 版本變更影響回溯

閘門決策路徑上沒有任何 LLM 呼叫。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..engine.impact_replay import get_impact_engine
from ..engine.knowledge import get_kb
from ..engine.passport import audit_completeness, is_audit_complete
from ..engine.rules import get_rule_engine
from ..models import (
    AnswerPassport,
    ConsultRequest,
    ConsultResponse,
    Role,
    SourcePassage,
    VetSearchRequest,
    VetSearchResponse,
)
from ..store.audit import get_store
from .service import get_service

router = APIRouter(prefix="/api")

# --------------------------------------------------------------------------
# 獸醫身分驗證 (Demo 版：靜態 token；正式版接 PKI／獸醫師執照 API)
# --------------------------------------------------------------------------
VET_TOKEN = os.environ.get("VETLINK_VET_TOKEN", "demo-vet-token")
ADMIN_TOKEN = os.environ.get("VETLINK_ADMIN_TOKEN", "demo-admin-token")


def _normalize_token(raw: Optional[str]) -> Optional[str]:
    """接受 `X-Vet-Token: <t>` 或 `Authorization: Bearer <t>` 兩種形式。"""
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw or None


def _verify_vet(x_vet_token: Optional[str], authorization: Optional[str]) -> str:
    """回傳已驗證的角色字串；未通過一律 403。"""
    token = _normalize_token(x_vet_token) or _normalize_token(authorization)
    if token is None:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "vet_verification_required",
                "message": "藍色專業模式需完成獸醫身分驗證，請提供 X-Vet-Token。",
                "rule_id": "VG-ROL-450",
            },
        )
    if token == ADMIN_TOKEN:
        return "admin"
    if token == VET_TOKEN:
        return "vet"
    raise HTTPException(
        status_code=403,
        detail={
            "error": "invalid_vet_token",
            "message": "獸醫身分驗證失敗。",
            "rule_id": "VG-ROL-450",
        },
    )


# --------------------------------------------------------------------------
# 健康檢查 / 統計
# --------------------------------------------------------------------------
@router.get("/health")
def health() -> Dict[str, Any]:
    kb = get_kb()
    rules = get_rule_engine()
    return {
        "status": "ok",
        "service": "vetlink-ai",
        "engine_version": "1.0.0",
        "rules_bundle_version": rules.bundle_version,
        "rule_count": len(rules.rules),
        "knowledge_source": kb.stats["source"],
        "product_count": kb.stats["product_count"],
        "as_of": kb.stats["as_of"],
        "llm_in_gate_path": False,
    }


@router.get("/stats")
def stats() -> Dict[str, Any]:
    kb = get_kb()
    rules = get_rule_engine()
    store = get_store()
    by_severity: Dict[str, int] = {}
    for r in rules.rules:
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
    return {
        "knowledge": kb.stats,
        "rules": {
            "bundle_version": rules.bundle_version,
            "total": len(rules.rules),
            "by_severity": by_severity,
        },
        "audit": store.stats(),
        # 效期閘門的關鍵證據：只能靠日期換算才抓得到的過期文件
        "expiry_gate": {
            "date_only_expired_count": kb.stats["date_only_expired_count"],
            "examples": kb.marker_disagreements[:5],
            "note": "來源未標示 (已失效)，僅能以民國日期換算後與 as-of 比較才判定過期。",
        },
    }


# --------------------------------------------------------------------------
# 第一幕：飼主端諮詢
# --------------------------------------------------------------------------
@router.post("/consult", response_model=ConsultResponse)
def consult(
    req: ConsultRequest,
    x_vet_token: Optional[str] = Header(default=None, alias="X-Vet-Token"),
    authorization: Optional[str] = Header(default=None),
    owner_authorized: bool = Query(default=False, description="飼主是否已授權獸醫存取個案"),
    requested_mode: Optional[str] = Query(default=None, description="要求解鎖的模式，如 blue"),
) -> ConsultResponse:
    # 角色升級必須靠 token，不能靠請求 body 自稱
    vet_verified = False
    if x_vet_token or authorization:
        try:
            _verify_vet(x_vet_token, authorization)
            vet_verified = True
        except HTTPException:
            vet_verified = False

    # 自稱獸醫但沒有有效 token → 拒絕，不得以 body 自我宣告角色
    effective_req = req
    if req.role in (Role.VET, Role.ADMIN) and not vet_verified:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "vet_verification_required",
                "message": "以獸醫或管理者角色送出諮詢需通過身分驗證。",
                "rule_id": "VG-ROL-450",
            },
        )

    service = get_service()
    response = service.consult(
        effective_req,
        vet_verified=vet_verified,
        owner_authorized=owner_authorized,
        requested_mode=requested_mode,
    )

    get_store().record_answer(
        passport=response.passport,
        request_payload=req.model_dump(mode="json"),
        response_payload=response.model_dump(mode="json"),
    )
    return response


# --------------------------------------------------------------------------
# 第二幕：獸醫端產品檢索 (藍色模式)
# --------------------------------------------------------------------------
@router.post("/vet/search", response_model=VetSearchResponse)
def vet_search(
    req: VetSearchRequest,
    x_vet_token: Optional[str] = Header(default=None, alias="X-Vet-Token"),
    authorization: Optional[str] = Header(default=None),
    role: Role = Query(default=Role.VET, description="宣稱角色；飼主一律拒絕"),
) -> VetSearchResponse:
    # 1) 角色層：飼主永遠不得使用藍色模式產品檢索
    if role == Role.OWNER:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "role_not_permitted",
                "message": "飼主角色不得存取獸醫專業模式產品檢索。",
                "rule_id": "VG-ROL-450",
            },
        )

    # 2) 身分層：必須有有效 token (無 token → 403)
    verified_role = _verify_vet(x_vet_token, authorization)
    effective_role = Role.ADMIN if verified_role == "admin" else Role.VET

    service = get_service()
    response, authorized = service.vet_search(
        req, role=effective_role, vet_verified=True
    )

    # 3) 個案資料需飼主授權 (VG-ROL-451)
    if not authorized:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "authorization_required",
                "message": response.passport.refusal_detail
                or "需取得飼主授權後才能存取個案資料。",
                "rule_id": "VG-ROL-451",
                "audit_id": response.audit_id,
            },
        )

    get_store().record_answer(
        passport=response.passport,
        request_payload=req.model_dump(mode="json"),
        response_payload={"result_count": len(response.results)},
    )
    return response


# --------------------------------------------------------------------------
# 回答護照回查
# --------------------------------------------------------------------------
@router.get("/passport/{audit_id}")
def get_passport(audit_id: str) -> Dict[str, Any]:
    passport = get_store().get_passport(audit_id)
    if passport is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"查無稽核編號 {audit_id}"},
        )
    record = get_store().get_answer_record(audit_id) or {}
    return {
        "passport": passport.model_dump(mode="json"),
        "audit_completeness": audit_completeness(passport),
        "is_audit_complete": is_audit_complete(passport),
        "status": record.get("status"),
        "fingerprint": record.get("fingerprint"),
    }


@router.get("/answers")
def list_answers(limit: int = Query(default=50, ge=1, le=500)) -> Dict[str, Any]:
    return {"answers": get_store().list_answers(limit=limit)}


# --------------------------------------------------------------------------
# 第三幕：Impact Replay
# --------------------------------------------------------------------------
class ImpactReplayRequest(BaseModel):
    """管理端上傳新版仿單，觸發變更影響回溯 (提案 §九)。"""

    doc_id: str
    old_version: str = ""
    new_version: str = ""
    old_passages: List[SourcePassage] = Field(default_factory=list)
    new_passages: List[SourcePassage] = Field(default_factory=list)
    notify: bool = True
    # 便利模式：不提供 old_passages 時，直接由知識庫取該文件現況作為舊版
    use_kb_as_old: bool = False


@router.post("/admin/impact-replay")
def impact_replay(
    payload: ImpactReplayRequest,
    x_vet_token: Optional[str] = Header(default=None, alias="X-Vet-Token"),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    token = _normalize_token(x_vet_token) or _normalize_token(authorization)
    if token != ADMIN_TOKEN:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "admin_required",
                "message": "Impact Replay 僅限中化管理者角色執行。",
            },
        )

    old_passages = list(payload.old_passages)
    if payload.use_kb_as_old and not old_passages:
        kb = get_kb()
        old_passages = [
            p for p in kb.passages.values() if p.doc_id == payload.doc_id
        ]

    if not old_passages and not payload.new_passages:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "empty_payload",
                "message": "需提供 old_passages 或 new_passages 至少其一。",
            },
        )

    report = get_impact_engine().run(
        doc_id=payload.doc_id,
        old_passages=old_passages,
        new_passages=payload.new_passages,
        old_version=payload.old_version,
        new_version=payload.new_version,
        notify=payload.notify,
    )
    return report.to_dict()


@router.get("/admin/impact-events")
def impact_events(limit: int = Query(default=100, ge=1, le=500)) -> Dict[str, Any]:
    return {"events": get_store().list_impact_events(limit=limit)}
