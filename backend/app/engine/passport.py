"""VetLink AI — 回答護照 (提案 §八).

每一次回答都攜帶：回答狀態、適用角色、觸發規則（成立與未成立）、支持來源（主張級）、
文件版本、適用範圍、拒絕原因、稽核編號。

主張級 (claim-level)，非文件級：每一項主張各自綁定支持它的來源段落。
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from ..models import (
    STATE_LABELS_ZH,
    AnswerPassport,
    CheckResult,
    ClaimBinding,
    DocumentVersionRef,
    GateState,
    RefusalReason,
    Role,
    RuleRef,
)

ENGINE_VERSION = "1.0.0"


def new_audit_id(prefix: str = "VL") -> str:
    """稽核編號：時間前綴 + 隨機碼，可回查完整輸入與攔截紀錄。"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{ts}-{uuid.uuid4().hex[:8].upper()}"


def _dedupe_docs(bindings: Sequence[ClaimBinding]) -> List[DocumentVersionRef]:
    """從主張綁定彙整文件版本清單。"""
    seen: Dict[str, DocumentVersionRef] = {}
    for b in bindings:
        for p in b.passages:
            key = f"{p.doc_id}@{p.version}"
            if key not in seen:
                seen[key] = DocumentVersionRef(
                    doc_id=p.doc_id,
                    version=p.version,
                    issue_date_iso=p.issue_date_iso,
                    expiry_date_iso=p.expiry_date_iso,
                    last_reviewed_at=p.issue_date_iso,
                    is_expired=p.is_expired,
                )
    return list(seen.values())


def build_passport(
    *,
    audit_id: Optional[str] = None,
    state: GateState,
    role: Role,
    checks: Sequence[CheckResult],
    claim_bindings: Sequence[ClaimBinding],
    applicable_scope: Dict[str, Any],
    refusal_reason: RefusalReason = RefusalReason.NONE,
    refusal_detail: str = "",
    rules_bundle_version: str = "",
    document_versions: Optional[Sequence[DocumentVersionRef]] = None,
) -> AnswerPassport:
    """組裝回答護照。所有必要欄位皆由此處填齊。"""
    fired: List[RuleRef] = []
    failed: List[RuleRef] = []
    for c in checks:
        fired.extend(c.rules_fired)
        failed.extend(c.rules_failed)

    # 去重 (同一規則可能被多個檢查引用)
    fired = _dedupe_rules(fired)
    failed = _dedupe_rules(failed)

    docs = list(document_versions) if document_versions is not None else _dedupe_docs(claim_bindings)

    return AnswerPassport(
        audit_id=audit_id or new_audit_id(),
        answer_state=state,
        answer_state_label_zh=STATE_LABELS_ZH[state.value],
        applicable_role=role,
        rules_fired=fired,
        rules_failed=failed,
        claim_bindings=list(claim_bindings),
        document_versions=docs,
        applicable_scope=applicable_scope,
        refusal_reason=refusal_reason,
        refusal_detail=refusal_detail,
        checks=list(checks),
        engine_version=ENGINE_VERSION,
        rules_bundle_version=rules_bundle_version,
    )


def _dedupe_rules(refs: Sequence[RuleRef]) -> List[RuleRef]:
    seen: Dict[str, RuleRef] = {}
    for r in refs:
        if r.rule_id not in seen:
            seen[r.rule_id] = r
    return list(seen.values())


def passport_fingerprint(passport: AnswerPassport) -> str:
    """護照內容指紋，用於 Impact Replay 比對重驗前後是否改變。"""
    parts = [
        passport.answer_state.value,
        passport.applicable_role.value,
        passport.refusal_reason.value,
        "|".join(sorted(f"{r.rule_id}@{r.version}" for r in passport.rules_fired)),
        "|".join(sorted(f"{d.doc_id}@{d.version}" for d in passport.document_versions)),
        "|".join(sorted(f"{b.claim_id}:{int(b.supported)}" for b in passport.claim_bindings)),
    ]
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:16]


def cited_passage_ids(passport: AnswerPassport) -> List[str]:
    """此回答引用過的所有來源段落 ID — Impact Replay 影響查找的索引鍵。"""
    ids: List[str] = []
    for b in passport.claim_bindings:
        for p in b.passages:
            if p.passage_id not in ids:
                ids.append(p.passage_id)
    return ids


def audit_completeness(passport: AnswerPassport) -> Dict[str, bool]:
    """提案 §12.1『回答具完整稽核紀錄 100%』的逐欄位檢查。"""
    return {
        "audit_id": bool(passport.audit_id),
        "answer_state": bool(passport.answer_state_label_zh),
        "applicable_role": bool(passport.applicable_role),
        "triggered_rules": bool(passport.rules_fired or passport.rules_failed),
        "supporting_sources": bool(
            passport.claim_bindings or passport.refusal_reason != RefusalReason.NONE
        ),
        "document_versions": bool(
            passport.document_versions or passport.refusal_reason != RefusalReason.NONE
        ),
        "applicable_scope": bool(passport.applicable_scope),
        "refusal_reason": (
            bool(passport.refusal_detail)
            if passport.refusal_reason != RefusalReason.NONE
            else True
        ),
        "rules_bundle_version": bool(passport.rules_bundle_version),
    }


def is_audit_complete(passport: AnswerPassport) -> bool:
    return all(audit_completeness(passport).values())
