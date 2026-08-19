"""VetLink AI — 服務層：把 Evidence Gate 決策組裝為可回傳的回答與護照。

流程 (提案 §六：先取得回答資格，再產生內容)：
    structure_case → gate.decide → 依「允許的輸出型別」組裝內容 → 主張驗證
    → build_passport → 政策文字掃描 → record_answer

**本模組不呼叫 LLM。** 所有輸出文字均取自獸醫審核過的來源段落與規則的
owner_message 欄位；因此每一句話都能對應到護照中的來源。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..engine import policy
from ..engine.claim_verifier import make_claim
from ..engine.knowledge import KnowledgeBase, get_kb
from ..engine.passport import build_passport, new_audit_id
from ..engine.rules import Rule, RuleEngine, get_rule_engine
from ..engine.state import EvidenceGate, GateContext, GateDecision, get_gate
from ..engine.structurer import structure_case
from ..models import (
    STATE_LABELS_ZH,
    AnswerPassport,
    Claim,
    ClaimBinding,
    ConsultRequest,
    ConsultResponse,
    GateState,
    ProductCard,
    RefusalReason,
    Role,
    SourcePassage,
    VetSearchRequest,
    VetSearchResponse,
)

# 每個狀態的標題 — 固定文案，不由模型生成
HEADLINES: Dict[GateState, str] = {
    GateState.RED: "紅色｜不得推薦：這個情況需要立即就醫",
    GateState.YELLOW: "黃色｜資訊不足：需要先補齊幾項必要資訊",
    GateState.GREEN: "綠色｜飼主可見：以下為經獸醫審核的衛教資訊",
    GateState.BLUE: "藍色｜獸醫專業模式：已解鎖核准仿單與產品資訊",
}

# 情境 → 衛教段落檢索關鍵詞
SCENARIO_QUERY: Dict[str, str] = {
    "泌尿": "排尿 砂盆 飲水 尿量",
    "腸胃": "嘔吐 腹瀉 食慾 飲水",
    "皮膚耳部": "搔癢 皮膚 耳道 分泌物",
    "呼吸": "呼吸 咳嗽 噴嚏 黏膜",
    "跨情境": "就醫 觀察 危險徵兆",
}

# 拒絕原因 → 飼主可讀說明
REFUSAL_MESSAGE: Dict[RefusalReason, str] = {
    RefusalReason.EMERGENCY: "系統偵測到急症紅旗，已停止產品檢索與用藥建議，請立即就醫。",
    RefusalReason.INSUFFICIENT_INFO: "目前資訊不足以安全判斷，系統只會提出必要問題，不會直接給答案。",
    RefusalReason.ROLE_MISMATCH: "此內容僅限已驗證身分的獸醫端查看。",
    RefusalReason.INSUFFICIENT_EVIDENCE: "找不到通過效期與審核閘門的來源段落，依證據資格規則拒答並交回獸醫。",
    RefusalReason.SOURCE_CONFLICT: "來源之間存在未解決的衝突，系統不擅自選擇其一，改為交回獸醫判斷。",
    RefusalReason.POLICY_VIOLATION: "依動物用藥品管理法與角色政策，此類內容不得對飼主輸出。",
}


class ConsultService:
    """飼主端諮詢與獸醫端檢索的組裝層。"""

    def __init__(
        self,
        gate: Optional[EvidenceGate] = None,
        kb: Optional[KnowledgeBase] = None,
        rules: Optional[RuleEngine] = None,
    ):
        self.gate = gate or get_gate()
        self.kb = kb or get_kb()
        self.rules = rules or get_rule_engine()

    # ------------------------------------------------------------------
    # 飼主端諮詢
    # ------------------------------------------------------------------
    def consult(
        self,
        req: ConsultRequest,
        *,
        vet_verified: bool = False,
        owner_authorized: bool = False,
        requested_mode: Optional[str] = None,
    ) -> ConsultResponse:
        facts = structure_case(req)

        # 1) 先取得候選來源與主張 —— 證據資格檢查需要它們
        candidate_passages = self._candidate_passages(facts)
        claims = self._build_claims(facts, candidate_passages)

        ctx = GateContext(
            facts=facts,
            role=req.role,
            vet_verified=vet_verified,
            owner_authorized=owner_authorized,
            requested_mode=requested_mode,
            requires_case_data=bool(requested_mode == "blue"),
            claims=claims,
            candidate_passages=candidate_passages,
        )

        # 2) 閘門判定 (確定性，無 LLM)
        decision = self.gate.decide(ctx)

        # 3) 依允許的輸出型別組裝內容
        messages, danger_signs, bindings = self._compose(decision, ctx, facts)

        # 4) 政策文字層最終防線：任何違規句子直接刪除
        safe_messages: List[str] = []
        violations: List[str] = []
        for m in messages:
            cleaned, v = policy.redact(req.role, m)
            violations.extend(v)
            if cleaned:
                safe_messages.append(cleaned)
        if violations:
            safe_messages.append(
                "（系統政策層已移除 " + str(len(violations)) + " 段不符合飼主端規範的內容。）"
            )

        audit_id = new_audit_id()
        passport = build_passport(
            audit_id=audit_id,
            state=decision.state,
            role=req.role,
            checks=decision.checks,
            claim_bindings=bindings,
            applicable_scope=decision.applicable_scope,
            refusal_reason=decision.refusal_reason,
            refusal_detail=decision.refusal_detail,
            rules_bundle_version=self.rules.bundle_version,
        )

        return ConsultResponse(
            audit_id=audit_id,
            state=decision.state,
            state_label_zh=STATE_LABELS_ZH[decision.state.value],
            headline=HEADLINES[decision.state],
            messages=safe_messages,
            required_questions=decision.required_questions,
            danger_signs=danger_signs,
            allowed_output_types=decision.allowed_output_types,
            blocked_output_types=decision.blocked_output_types,
            product_retrieval_halted=decision.product_retrieval_halted,
            visit_summary=self._visit_summary(facts, decision),
            passport=passport,
        )

    # ------------------------------------------------------------------
    # 候選來源與主張
    # ------------------------------------------------------------------
    def _candidate_passages(self, facts: Dict[str, Any]) -> List[SourcePassage]:
        """依情境檢索獸醫審核衛教段落。只取通過效期閘門者。"""
        species = facts.get("species")
        species = species if species in ("cat", "dog") else None
        out: List[SourcePassage] = []
        seen = set()
        for scenario in facts.get("scenarios") or ["跨情境"]:
            query = SCENARIO_QUERY.get(scenario, scenario)
            for p in self.kb.search_passages(query, species=species, limit=4):
                if p.passage_id not in seen and p.passage_id.startswith("EDU-"):
                    seen.add(p.passage_id)
                    out.append(p)

        # 政策／毒理／急症段落一律納入候選，讓相關主張找得到來源
        for pid in ("EDU-POL-001", "EDU-POL-002", "EDU-TOX-001", "EDU-TOX-002",
                    "EDU-EMG-001", "EDU-EMG-002", "EDU-EMG-003"):
            p = self.kb.get_passage(pid)
            if p and p.passage_id not in seen and not p.is_expired:
                seen.add(pid)
                out.append(p)
        return out

    def _build_claims(
        self, facts: Dict[str, Any], passages: Sequence[SourcePassage]
    ) -> List[Claim]:
        """主張直接取自來源段落原文 —— 因此必然可被該段落支持。

        這是「受控生成」的核心：系統不改寫醫療內容，只選擇要輸出哪些已審核段落。
        任何無法對應到來源的內容根本不會被產生。
        """
        claims: List[Claim] = []
        for i, p in enumerate(passages[:6], start=1):
            claims.append(
                make_claim(
                    claim_id=f"C{i:02d}",
                    text=p.text,
                    claim_type="medical",
                    passage_ids=[p.passage_id],
                )
            )
        return claims

    # ------------------------------------------------------------------
    # 內容組裝 —— 嚴格依 allowed_output_types 白名單
    # ------------------------------------------------------------------
    def _compose(
        self, decision: GateDecision, ctx: GateContext, facts: Dict[str, Any]
    ) -> Tuple[List[str], List[str], List[ClaimBinding]]:
        allowed = set(decision.allowed_output_types)
        messages: List[str] = []
        danger: List[str] = []

        # 拒絕原因說明 —— 拒答時一律說明理由 (提案 §八：拒絕原因為護照必要欄位)
        if decision.refusal_reason != RefusalReason.NONE:
            msg = REFUSAL_MESSAGE.get(decision.refusal_reason)
            if msg:
                messages.append(msg)

        # 規則的 owner_message —— 已由獸醫審核的固定文案
        for rule in decision.fired_rules:
            om = getattr(rule, "owner_message", "") or ""
            if om.strip():
                messages.append(om.strip())

        if "emergency_referral" in allowed:
            messages.append("請立即聯繫或前往動物醫院急診，勿在家自行給藥或觀察等待。")
        if "vet_referral" in allowed and "emergency_referral" not in allowed:
            messages.append("建議由執業獸醫師診斷後再決定是否用藥。")
        if "required_questions" in allowed and decision.required_questions:
            messages.append("為了安全判斷，請先回答下列必要問題：")

        # 危險徵兆 / 衛教內容 —— 一律取自已驗證主張的來源段落
        bindings = self._verified_bindings(decision, ctx)
        supported_texts = [
            p.text for b in bindings if b.supported for p in b.passages
        ]
        supported_texts = list(dict.fromkeys(supported_texts))

        if "danger_signs" in allowed:
            danger = [t for t in supported_texts if any(
                k in t for k in ("立即", "危險", "危及生命", "急診", "儘速")
            )][:4]
        if "education" in allowed or "observation_checklist" in allowed:
            edu = [t for t in supported_texts if t not in danger][:3]
            messages.extend(edu)

        return messages, danger, bindings

    def _verified_bindings(
        self, decision: GateDecision, ctx: GateContext
    ) -> List[ClaimBinding]:
        """取得主張綁定。優先使用閘門已完成的驗證結果，避免重複計算。"""
        if decision.verification is not None:
            return decision.verification.bindings
        usable = [
            p for p in ctx.candidate_passages
            if not p.is_expired and p.review_status == "approved"
        ]
        if not ctx.claims:
            return []
        return self.gate.verifier.verify(ctx.claims, usable).bindings

    @staticmethod
    def _visit_summary(facts: Dict[str, Any], decision: GateDecision) -> Optional[Dict[str, Any]]:
        """就診摘要 (提案 §十一 P1) — 供飼主帶去給獸醫。"""
        if "visit_summary" not in set(decision.allowed_output_types):
            return None
        return {
            "species": facts.get("species"),
            "symptoms": facts.get("symptoms") or [],
            "duration_hours": facts.get("duration_hours"),
            "body_weight_kg": facts.get("body_weight_kg"),
            "current_medications": facts.get("current_medications"),
            "gate_state": decision.state.value,
            "fired_rules": [r.rule_id for r in decision.fired_rules],
            "note": "本摘要由確定性規則產生，供獸醫問診參考，不構成診斷。",
        }

    # ------------------------------------------------------------------
    # 獸醫端產品檢索 (藍色模式)
    # ------------------------------------------------------------------
    def vet_search(
        self,
        req: VetSearchRequest,
        *,
        role: Role,
        vet_verified: bool,
    ) -> Tuple[VetSearchResponse, bool]:
        """回傳 (回應, 是否已授權)。未授權時回應僅含拒絕原因與空結果。"""
        species = req.species.value if req.species else None
        facts: Dict[str, Any] = {
            "species": species or "unknown",
            "role": role.value,
            "intent": "general",
            "scenarios": ["跨情境"],
            "symptoms": [],
        }

        ctx = GateContext(
            facts=facts,
            role=role,
            vet_verified=vet_verified,
            owner_authorized=req.owner_authorized,
            requested_mode="blue",
            requires_case_data=bool(req.case_audit_id),
            claims=[],
            candidate_passages=[],
        )
        decision = self.gate.decide(ctx)
        authorized = decision.state == GateState.BLUE and role in (Role.VET, Role.ADMIN)

        audit_id = new_audit_id("VS")
        results: List[ProductCard] = []
        expired: List[ProductCard] = []
        bindings: List[ClaimBinding] = []

        if authorized:
            results, expired = self.kb.search_products(
                query=req.query,
                species=species,
                indication=req.indication,
                ingredient=req.ingredient,
                dosage_form=req.dosage_form,
                limit=req.limit,
            )
            # 每張產品卡對應一項主張，綁定其許可證來源段落
            for i, card in enumerate(results, start=1):
                p = self.kb.get_passage(f"PROD-{card.licence_no}")
                if p is None:
                    continue
                bindings.append(
                    ClaimBinding(
                        claim_id=f"P{i:02d}",
                        claim_text=f"{card.name_zh}（{card.licence_no}）核准適應症與成分如來源段落所載。",
                        claim_type="product",
                        supported=True,
                        passages=[p],
                        note="主張內容直接取自農業部開放資料許可證欄位。",
                    )
                )

        passport = build_passport(
            audit_id=audit_id,
            state=decision.state,
            role=role,
            checks=decision.checks,
            claim_bindings=bindings,
            applicable_scope=decision.applicable_scope,
            refusal_reason=decision.refusal_reason,
            refusal_detail=decision.refusal_detail
            or ("" if authorized else "未通過藍色模式角色資格檢查。"),
            rules_bundle_version=self.rules.bundle_version,
        )

        response = VetSearchResponse(
            audit_id=audit_id,
            state=decision.state,
            state_label_zh=STATE_LABELS_ZH[decision.state.value],
            results=results,
            excluded_expired_count=len(expired),
            excluded_expired_licences=[p.licence_no for p in expired],
            passport=passport,
        )
        return response, authorized


_SERVICE: Optional[ConsultService] = None


def get_service(reload: bool = False) -> ConsultService:
    global _SERVICE
    if _SERVICE is None or reload:
        _SERVICE = ConsultService()
    return _SERVICE
