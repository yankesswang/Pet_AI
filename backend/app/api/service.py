"""VetLink AI — 服務層：把 Evidence Gate 決策組裝為可回傳的回答與護照。

流程 (提案 §六：先取得回答資格，再產生內容)：
    structure_case → gate.decide → 依「允許的輸出型別」組裝內容 → 主張驗證
    → build_passport → 政策文字掃描 → record_answer

所有輸出文字均取自獸醫審核過的來源段落與規則的 owner_message 欄位；
因此每一句話都能對應到護照中的來源。

**閘門決策路徑不呼叫 LLM。** 本模組唯一可能觸發 LLM 的是最後一步的
衛教語言轉譯（`_translate`），它發生在狀態判定與內容選取「之後」，
只改寫顯示文字，且改寫結果仍須通過涵蓋度檢查與角色政策掃描；
旗標關閉（預設）或無金鑰時直接回傳段落原文。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..engine import policy
from ..engine.claim_verifier import make_claim
from ..engine.knowledge import KnowledgeBase, get_kb
from ..engine.passport import build_passport, new_audit_id
from ..engine.rules import Rule, RuleEngine, get_rule_engine
from ..engine.state import EvidenceGate, GateContext, GateDecision, get_gate
from ..engine.structurer import structure_case
from ..llm.structurer_llm import structure_case_llm
from ..llm.translator_llm import rewrite_passages, translation_status
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

# 政策／毒理／急症段落：任何情境都可能需要，一律納入候選
# （仍須通過效期與物種閘門）。
ALWAYS_CANDIDATE_PASSAGES: Tuple[str, ...] = (
    "EDU-POL-001", "EDU-POL-002", "EDU-TOX-001", "EDU-TOX-002",
    "EDU-EMG-001", "EDU-EMG-002", "EDU-EMG-003",
)

# 一次回答最多產生幾項主張。超出的候選段落不會被輸出，
# 但仍會出現在檢索軌跡裡（stage=candidate），以免看起來像被系統吃掉。
CLAIM_LIMIT = 6

# 拒絕原因 → 飼主可讀說明
REFUSAL_MESSAGE: Dict[RefusalReason, str] = {
    RefusalReason.EMERGENCY: "系統偵測到急症紅旗，已停止產品檢索與用藥建議，請立即就醫。",
    RefusalReason.INSUFFICIENT_INFO: "目前資訊不足以安全判斷，系統只會提出必要問題，不會直接給答案。",
    RefusalReason.ROLE_MISMATCH: "此內容僅限已驗證身分的獸醫端查看。",
    RefusalReason.INSUFFICIENT_EVIDENCE: "找不到通過效期與審核閘門的來源段落，依證據資格規則拒答並交回獸醫。",
    RefusalReason.SOURCE_CONFLICT: "來源之間存在未解決的衝突，系統不擅自選擇其一，改為交回獸醫判斷。",
    RefusalReason.POLICY_VIOLATION: "依動物用藥品管理法與角色政策，此類內容不得對飼主輸出。",
}


@dataclass
class ComposedContent:
    """`_compose` 的結果。

    刻意把「顯示了哪些段落」一起帶出來：檢索軌跡要能區分
    檢索到（candidate）／成為主張（claim）／真的講出來（displayed）三件事，
    只看 claim_bindings 是分不出來的。
    """

    messages: List[str]
    danger_signs: List[str]
    bindings: List[ClaimBinding]
    displayed_passage_ids: List[str]
    translation: Optional[Dict[str, Any]] = None


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
        # 症狀結構化：旗標關閉（預設）時等同 structure_case；
        # 開啟時 LLM 抽取結果須先通過 Schema 驗證與安全合併，才會進入閘門。
        facts = structure_case_llm(req)

        # 1) 先取得候選來源與主張 —— 證據資格檢查需要它們
        candidate_passages, excluded_passages = self._retrieve(facts)
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
        composed = self._compose(decision, ctx, facts)

        # 4) 政策文字層最終防線：任何違規句子直接刪除
        safe_messages: List[str] = []
        violations: List[str] = []
        for m in composed.messages:
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
            claim_bindings=composed.bindings,
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
            danger_signs=composed.danger_signs,
            allowed_output_types=decision.allowed_output_types,
            blocked_output_types=decision.blocked_output_types,
            product_retrieval_halted=decision.product_retrieval_halted,
            visit_summary=self._visit_summary(facts, decision),
            llm_translation=composed.translation,
            retrieval=self._retrieval_trace(
                facts,
                candidate_passages,
                excluded_passages,
                claims,
                composed,
                library_total=sum(
                    1 for pid in self.kb.passages if pid.startswith("EDU-")
                ),
            ),
            passport=passport,
        )

    # ------------------------------------------------------------------
    # 候選來源與主張
    # ------------------------------------------------------------------
    def _candidate_passages(self, facts: Dict[str, Any]) -> List[SourcePassage]:
        """依情境取獸醫審核衛教段落。只取通過效期閘門者。"""
        return self._retrieve(facts)[0]

    def _retrieve(
        self, facts: Dict[str, Any]
    ) -> Tuple[List[SourcePassage], List[Dict[str, str]]]:
        """回傳 (候選段落, 被排除的段落與原因)。

        情境比對先走段落的 `scenario_scope` 標註，再於同情境內依提問排序 ——
        關鍵字計分沒有最低門檻，會讓「食慾」「飲水」這類通用詞把不相關情境
        的段落帶進候選（見 `KnowledgeBase.education_passages`）。

        排除清單不是除錯輸出，是**產品的一部分**：使用者要能看到系統從整個
        文件庫裡挑了什麼、又為什麼沒挑其他的。沒有這份清單，「只講有來源的話」
        就只是一句宣稱。
        """
        species = facts.get("species")
        species = species if species in ("cat", "dog") else None
        scenarios = facts.get("scenarios") or ["跨情境"]

        out: List[SourcePassage] = []
        seen = set()
        for scenario in scenarios:
            for p in self.kb.education_passages(
                scenario,
                species=species,
                query=str(facts.get("raw_text") or ""),
            ):
                if p.passage_id not in seen and p.passage_id.startswith("EDU-"):
                    seen.add(p.passage_id)
                    out.append(p)

        # 政策／毒理／急症段落一律納入候選，讓相關主張找得到來源。
        # 物種過濾仍要套用：EDU-EMG-001 是貓專屬的尿道阻塞衛教，
        # 不加過濾會讓狗的案例拿到貓的內容。
        for pid in ALWAYS_CANDIDATE_PASSAGES:
            p = self.kb.get_passage(pid)
            if p is None or p.passage_id in seen or p.is_expired:
                continue
            if species and p.species_scope and species not in p.species_scope:
                continue
            seen.add(pid)
            out.append(p)

        excluded = self._exclusions(seen, scenarios, species)
        return out, excluded

    def _exclusions(
        self, chosen: set, scenarios: Sequence[str], species: Optional[str]
    ) -> List[Dict[str, str]]:
        """文件庫裡**沒有**被選中的衛教段落，逐段標明原因。"""
        out: List[Dict[str, str]] = []
        for pid, p in sorted(self.kb.passages.items()):
            if not pid.startswith("EDU-") or pid in chosen:
                continue
            if p.is_expired:
                reason = f"文件效期閘門排除（有效期至 {p.expiry_date_iso}）"
            elif p.review_status != "approved":
                reason = f"審核狀態為 {p.review_status}，未通過審核閘門"
            elif species and p.species_scope and species not in p.species_scope:
                reason = f"適用物種為 {'／'.join(p.species_scope)}，與本次案例不符"
            else:
                reason = (
                    f"情境不符（此段屬 {'／'.join(p.scenario_scope) or '未標註'}，"
                    f"本次判定為 {'／'.join(scenarios)}）"
                )
            out.append({
                "passage_id": pid,
                "doc_id": p.doc_id,
                "scenario_scope": "／".join(p.scenario_scope),
                "reason_zh": reason,
            })
        return out

    @staticmethod
    def _retrieval_trace(
        facts: Dict[str, Any],
        candidates: Sequence[SourcePassage],
        excluded: Sequence[Dict[str, str]],
        claims: Sequence[Claim],
        composed: "ComposedContent",
        library_total: int,
    ) -> Dict[str, Any]:
        """把「文件庫 → 候選 → 主張 → 實際輸出」四層漏斗攤開給前端。"""
        claim_by_passage = {
            pid: c.claim_id for c in claims for pid in c.supporting_passage_ids
        }
        supported = {
            p.passage_id
            for b in composed.bindings if b.supported
            for p in b.passages
        }
        displayed = set(composed.displayed_passage_ids)

        rows: List[Dict[str, Any]] = []
        for p in candidates:
            claim_id = claim_by_passage.get(p.passage_id)
            if p.passage_id in displayed:
                stage, stage_zh = "displayed", "已輸出給使用者"
            elif p.passage_id in supported:
                stage, stage_zh = "verified", "通過主張驗證，但未進入本次輸出型別"
            elif claim_id:
                stage, stage_zh = "unsupported", "成為主張但未通過驗證，已刪除"
            else:
                stage, stage_zh = "candidate", "檢索到但未成為主張（超出前 6 項上限）"
            rows.append({
                "passage_id": p.passage_id,
                "doc_id": p.doc_id,
                "version": p.version,
                "text": p.text,
                "scenario_scope": list(p.scenario_scope),
                "species_scope": list(p.species_scope),
                "issue_date_iso": p.issue_date_iso,
                "expiry_date_iso": p.expiry_date_iso,
                "is_expired": p.is_expired,
                "review_status": p.review_status,
                "claim_id": claim_id,
                "stage": stage,
                "stage_zh": stage_zh,
            })

        return {
            "scenarios": list(facts.get("scenarios") or []),
            "species": facts.get("species"),
            "method_zh": "情境標註比對（scenario_scope）後，以提問關鍵詞在同情境內排序",
            "claim_limit": CLAIM_LIMIT,
            "candidates": rows,
            "excluded": list(excluded),
            "counts": {
                "library": library_total,
                "candidates": len(rows),
                "claims": len(claims),
                "verified": len(supported),
                "displayed": len(displayed),
                "excluded": len(excluded),
            },
        }

    def _build_claims(
        self, facts: Dict[str, Any], passages: Sequence[SourcePassage]
    ) -> List[Claim]:
        """主張直接取自來源段落原文 —— 因此必然可被該段落支持。

        這是「受控生成」的核心：系統不改寫醫療內容，只選擇要輸出哪些已審核段落。
        任何無法對應到來源的內容根本不會被產生。
        """
        claims: List[Claim] = []
        for i, p in enumerate(passages[:CLAIM_LIMIT], start=1):
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
    ) -> "ComposedContent":
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
        supported: List[SourcePassage] = []
        seen_text = set()
        for b in bindings:
            if not b.supported:
                continue
            for p in b.passages:
                if p.text not in seen_text:
                    seen_text.add(p.text)
                    supported.append(p)

        # 分類一律用**段落原文**：危險徵兆的判定不可受語言轉譯影響，
        # 否則改寫掉「立即」兩個字就會讓一段危險徵兆被降級成一般衛教。
        danger_src: List[SourcePassage] = []
        if "danger_signs" in allowed:
            danger_src = [p for p in supported if any(
                k in p.text for k in ("立即", "危險", "危及生命", "急診", "儘速")
            )][:4]
        edu_src: List[SourcePassage] = []
        if "education" in allowed or "observation_checklist" in allowed:
            edu_src = [p for p in supported if p not in danger_src][:3]

        # 分類完成後才做語言轉譯（提案 §7.1 第二處 LLM 介入點）。
        # 旗標關閉或無金鑰時 rewrite_passages 直接回傳原文，行為與未接入時相同；
        # 改寫結果仍須通過涵蓋度檢查與角色政策掃描，任一關失敗即退回原文。
        display, translation = self._translate(danger_src + edu_src, ctx.role)

        danger = [display[p.passage_id] for p in danger_src]
        messages.extend(display[p.passage_id] for p in edu_src)

        return ComposedContent(
            messages=messages,
            danger_signs=danger,
            bindings=bindings,
            # 實際被輸出到畫面上的段落 —— 檢索軌跡靠它區分
            # 「檢索到」「成為主張」「真的講出來」三件不同的事。
            displayed_passage_ids=[p.passage_id for p in danger_src + edu_src],
            translation=translation,
        )

    @staticmethod
    def _translate(
        passages: Sequence[SourcePassage], role: Role
    ) -> Tuple[Dict[str, str], Optional[Dict[str, Any]]]:
        """回傳 (passage_id → 顯示文字, 轉譯稽核摘要)。未啟用時即為段落原文。

        轉譯只影響**顯示文字**：主張綁定、護照引用與稽核紀錄一律保留段落原文
        與 passage_id，因此「這句話出自哪一段」不會因改寫而失真。
        """
        items = list(passages)
        if not items:
            return {}, None
        results = rewrite_passages(items, role=role, limit=len(items))
        return (
            {r["passage_id"]: r["text"] for r in results},
            translation_status(results),
        )

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
