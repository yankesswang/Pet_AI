"""VetLink AI — Impact Replay 變更影響回溯 (提案 §九).

當仿單、許可證、禁忌或法規更新時，自動執行五個步驟：
  1. 差異比對    標示新舊版本新增、刪除及變更段落
  2. 影響查找    找出曾引用舊段落的歷史回答
  3. 風險分級    高=立即失效、中=人工重審、低=更新標示
  4. 重新驗證    以新版本重新執行推薦資格與主張驗證
  5. 通知與稽核  通知管理者及受影響使用者，保留處理紀錄

不呼叫 LLM。差異比對使用 stdlib difflib。
"""
from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from ..models import AnswerPassport, RefusalReason, SourcePassage
from ..store.audit import AuditStore, get_store
from .claim_verifier import ClaimVerifier, get_verifier
from .knowledge import KnowledgeBase, get_kb


class RiskTier(str, Enum):
    HIGH = "high"    # 立即失效並通知
    MID = "mid"      # 進入人工重審
    LOW = "low"      # 僅更新版本標示


class DiffKind(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


# 高風險關鍵詞：涉及禁忌、物種限制、安全警語的變更一律高風險
HIGH_RISK_TOKENS = [
    "禁忌", "不得", "禁用", "毒性", "致命", "嚴重", "警語", "不可使用",
    "撤回", "回收", "停售", "停產", "失效", "過期",
    "貓", "犬", "物種", "孕", "幼齡", "腎", "肝",
    "劑量", "適應症", "處方",
]

MID_RISK_TOKENS = [
    "注意", "建議", "監測", "副作用", "不良反應", "交互作用", "保存",
]


@dataclass
class PassageDiff:
    passage_id: str
    doc_id: str
    kind: DiffKind
    old_text: str = ""
    new_text: str = ""
    old_version: str = ""
    new_version: str = ""
    similarity: float = 1.0
    changed_tokens: List[str] = field(default_factory=list)

    @property
    def is_material(self) -> bool:
        return self.kind != DiffKind.UNCHANGED


@dataclass
class AffectedAnswer:
    audit_id: str
    cited_passage_ids: List[str]
    risk_tier: RiskTier
    action: str
    detail: str
    revalidated_state: Optional[str] = None
    revalidation_changed: bool = False
    notified: bool = False


@dataclass
class ImpactReplayReport:
    replay_id: str
    doc_id: str
    old_version: str
    new_version: str
    created_at: str
    diffs: List[PassageDiff] = field(default_factory=list)
    affected: List[AffectedAnswer] = field(default_factory=list)
    candidate_answer_count: int = 0
    notified_count: int = 0

    @property
    def material_diffs(self) -> List[PassageDiff]:
        return [d for d in self.diffs if d.is_material]

    @property
    def by_tier(self) -> Dict[str, int]:
        out = {t.value: 0 for t in RiskTier}
        for a in self.affected:
            out[a.risk_tier.value] += 1
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "replay_id": self.replay_id,
            "doc_id": self.doc_id,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "created_at": self.created_at,
            "diff_summary": {
                "total": len(self.diffs),
                "material": len(self.material_diffs),
                "added": sum(1 for d in self.diffs if d.kind == DiffKind.ADDED),
                "removed": sum(1 for d in self.diffs if d.kind == DiffKind.REMOVED),
                "changed": sum(1 for d in self.diffs if d.kind == DiffKind.CHANGED),
            },
            "diffs": [
                {
                    "passage_id": d.passage_id,
                    "kind": d.kind.value,
                    "similarity": round(d.similarity, 3),
                    "changed_tokens": d.changed_tokens,
                    "old_text": d.old_text,
                    "new_text": d.new_text,
                }
                for d in self.diffs
                if d.is_material
            ],
            "candidate_answer_count": self.candidate_answer_count,
            "affected_count": len(self.affected),
            "by_risk_tier": self.by_tier,
            "notified_count": self.notified_count,
            "affected": [
                {
                    "audit_id": a.audit_id,
                    "cited_passage_ids": a.cited_passage_ids,
                    "risk_tier": a.risk_tier.value,
                    "action": a.action,
                    "detail": a.detail,
                    "revalidated_state": a.revalidated_state,
                    "revalidation_changed": a.revalidation_changed,
                    "notified": a.notified,
                }
                for a in self.affected
            ],
        }


class ImpactReplayEngine:
    """變更影響回溯引擎。"""

    def __init__(
        self,
        store: Optional[AuditStore] = None,
        kb: Optional[KnowledgeBase] = None,
        verifier: Optional[ClaimVerifier] = None,
    ):
        self.store = store or get_store()
        self.kb = kb or get_kb()
        self.verifier = verifier or get_verifier()

    # -- 步驟 1：差異比對 -------------------------------------------------
    def diff_versions(
        self,
        old_passages: Sequence[SourcePassage],
        new_passages: Sequence[SourcePassage],
    ) -> List[PassageDiff]:
        old_map = {p.passage_id: p for p in old_passages}
        new_map = {p.passage_id: p for p in new_passages}
        diffs: List[PassageDiff] = []

        for pid, old in old_map.items():
            new = new_map.get(pid)
            if new is None:
                diffs.append(
                    PassageDiff(
                        passage_id=pid,
                        doc_id=old.doc_id,
                        kind=DiffKind.REMOVED,
                        old_text=old.text,
                        old_version=old.version,
                        similarity=0.0,
                        changed_tokens=_risk_tokens(old.text),
                    )
                )
                continue
            if old.text == new.text:
                diffs.append(
                    PassageDiff(
                        passage_id=pid,
                        doc_id=old.doc_id,
                        kind=DiffKind.UNCHANGED,
                        old_text=old.text,
                        new_text=new.text,
                        old_version=old.version,
                        new_version=new.version,
                        similarity=1.0,
                    )
                )
                continue
            sim = difflib.SequenceMatcher(None, old.text, new.text).ratio()
            diffs.append(
                PassageDiff(
                    passage_id=pid,
                    doc_id=old.doc_id,
                    kind=DiffKind.CHANGED,
                    old_text=old.text,
                    new_text=new.text,
                    old_version=old.version,
                    new_version=new.version,
                    similarity=sim,
                    changed_tokens=_changed_risk_tokens(old.text, new.text),
                )
            )

        for pid, new in new_map.items():
            if pid not in old_map:
                diffs.append(
                    PassageDiff(
                        passage_id=pid,
                        doc_id=new.doc_id,
                        kind=DiffKind.ADDED,
                        new_text=new.text,
                        new_version=new.version,
                        similarity=0.0,
                        changed_tokens=_risk_tokens(new.text),
                    )
                )
        return diffs

    # -- 步驟 3：風險分級 -------------------------------------------------
    @staticmethod
    def classify_risk(diff: PassageDiff) -> RiskTier:
        """高=立即失效、中=人工重審、低=更新標示。"""
        if diff.kind == DiffKind.REMOVED:
            return RiskTier.HIGH
        if diff.changed_tokens:
            if any(t in HIGH_RISK_TOKENS for t in diff.changed_tokens):
                return RiskTier.HIGH
            if any(t in MID_RISK_TOKENS for t in diff.changed_tokens):
                return RiskTier.MID
        if diff.kind == DiffKind.CHANGED:
            # 大幅改寫視為中風險，僅措辭微調視為低風險
            return RiskTier.MID if diff.similarity < 0.85 else RiskTier.LOW
        if diff.kind == DiffKind.ADDED:
            return RiskTier.LOW
        return RiskTier.LOW

    # -- 主流程 -----------------------------------------------------------
    def run(
        self,
        doc_id: str,
        old_passages: Sequence[SourcePassage],
        new_passages: Sequence[SourcePassage],
        old_version: str = "",
        new_version: str = "",
        notify: bool = True,
    ) -> ImpactReplayReport:
        replay_id = f"IR-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
        report = ImpactReplayReport(
            replay_id=replay_id,
            doc_id=doc_id,
            old_version=old_version or (old_passages[0].version if old_passages else ""),
            new_version=new_version or (new_passages[0].version if new_passages else ""),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # 1. 差異比對
        report.diffs = self.diff_versions(old_passages, new_passages)
        material = report.material_diffs
        if not material:
            return report

        # 2. 影響查找
        changed_ids = [d.passage_id for d in material]
        affected_ids = self.store.find_answers_citing_passages(changed_ids)
        report.candidate_answer_count = len(affected_ids)

        # 每段落的風險分級
        tier_by_passage = {d.passage_id: self.classify_risk(d) for d in material}
        diff_by_passage = {d.passage_id: d for d in material}

        new_map = {p.passage_id: p for p in new_passages}

        for audit_id in affected_ids:
            passport = self.store.get_passport(audit_id)
            if passport is None:
                continue
            cited = [
                p.passage_id
                for b in passport.claim_bindings
                for p in b.passages
                if p.passage_id in tier_by_passage
            ]
            cited = list(dict.fromkeys(cited))
            if not cited:
                continue

            # 3. 取該回答受影響段落中的最高風險等級
            tier = _max_tier([tier_by_passage[pid] for pid in cited])

            # 4. 重新驗證：以新版本重跑主張驗證
            revalidated_state, changed = self._revalidate(passport, cited, new_map)

            action, detail = self._action_for(tier, changed, cited, diff_by_passage)

            # 高風險 → 立即失效
            if tier == RiskTier.HIGH:
                self.store.set_status(audit_id, "invalidated")
            elif tier == RiskTier.MID:
                self.store.set_status(audit_id, "pending_review")
            else:
                self.store.set_status(audit_id, "label_updated")

            affected = AffectedAnswer(
                audit_id=audit_id,
                cited_passage_ids=cited,
                risk_tier=tier,
                action=action,
                detail=detail,
                revalidated_state=revalidated_state,
                revalidation_changed=changed,
                notified=notify,
            )
            report.affected.append(affected)

            # 5. 通知與稽核
            self.store.record_impact_event(
                event_id=f"{replay_id}-{audit_id}",
                doc_id=doc_id,
                old_version=report.old_version,
                new_version=report.new_version,
                risk_tier=tier.value,
                affected_audit_id=audit_id,
                action=action,
                detail=detail,
                notified=notify,
            )
            if notify:
                report.notified_count += 1

        return report

    def _revalidate(
        self,
        passport: AnswerPassport,
        cited: Sequence[str],
        new_map: Dict[str, SourcePassage],
    ) -> tuple:
        """以新版段落重新執行主張驗證，回報結論是否改變。"""
        from ..models import Claim

        claims: List[Claim] = []
        for b in passport.claim_bindings:
            if any(p.passage_id in cited for p in b.passages):
                claims.append(
                    Claim(
                        claim_id=b.claim_id,
                        text=b.claim_text,
                        claim_type=b.claim_type,
                    )
                )
        if not claims:
            return None, False

        candidates = [new_map[pid] for pid in cited if pid in new_map]
        # 新版本已刪除該段落 → 主張必然失去支持
        if not candidates:
            return "unsupported", True

        result = self.verifier.verify(claims, candidates)
        still_supported = result.all_supported
        was_supported = all(
            b.supported for b in passport.claim_bindings if b.claim_id in {c.claim_id for c in claims}
        )
        return ("supported" if still_supported else "unsupported"), (still_supported != was_supported)

    @staticmethod
    def _action_for(
        tier: RiskTier,
        revalidation_changed: bool,
        cited: Sequence[str],
        diff_by_passage: Dict[str, PassageDiff],
    ) -> tuple:
        kinds = ", ".join(
            sorted({diff_by_passage[p].kind.value for p in cited if p in diff_by_passage})
        )
        if tier == RiskTier.HIGH:
            action = "invalidate_immediately"
            detail = f"高風險變更（{kinds}），回答立即失效並通知受影響使用者。"
        elif tier == RiskTier.MID:
            action = "human_re_review"
            detail = f"中風險變更（{kinds}），建立人工重審任務。"
        else:
            action = "update_label"
            detail = f"低風險變更（{kinds}），僅更新版本標示。"
        if revalidation_changed:
            detail += " 重新驗證結果與原回答不一致。"
        return action, detail


def _risk_tokens(text: str) -> List[str]:
    return [t for t in HIGH_RISK_TOKENS + MID_RISK_TOKENS if t in text]


def _changed_risk_tokens(old: str, new: str) -> List[str]:
    """只回報在新舊版之間「出現或消失」的風險關鍵詞。"""
    out: List[str] = []
    for t in HIGH_RISK_TOKENS + MID_RISK_TOKENS:
        if (t in old) != (t in new):
            out.append(t)
    return out


def _max_tier(tiers: Sequence[RiskTier]) -> RiskTier:
    order = {RiskTier.LOW: 0, RiskTier.MID: 1, RiskTier.HIGH: 2}
    return max(tiers, key=lambda t: order[t]) if tiers else RiskTier.LOW


_ENGINE: Optional[ImpactReplayEngine] = None


def get_impact_engine(reload: bool = False) -> ImpactReplayEngine:
    global _ENGINE
    if _ENGINE is None or reload:
        _ENGINE = ImpactReplayEngine()
    return _ENGINE
