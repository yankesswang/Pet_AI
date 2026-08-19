"""VetLink AI — Evidence Gate 四狀態機 (提案 §四).

RED    不得推薦     急症紅旗 → 完全停止產品檢索
YELLOW 資訊不足     缺物種/體重/時間/嚴重度/既有用藥 → 只問固定必要問題
GREEN  飼主可見     經審核衛教
BLUE   獸醫專業模式  獸醫身分驗證 + 飼主授權後解鎖

五項資格檢查（提案 §四）：安全資格、資料資格、角色資格、證據資格、一致性資格。

**此模組不呼叫 LLM。** 閘門決策完全確定性、可離線重現。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..models import (
    CHECK_LABELS_ZH,
    Claim,
    CheckId,
    CheckResult,
    GateState,
    RefusalReason,
    Role,
    RuleRef,
    Species,
    SourcePassage,
)
from . import policy
from .claim_verifier import ClaimVerifier, VerificationResult, get_verifier
from .knowledge import KnowledgeBase, get_kb
from .rules import Rule, RuleEngine, RuleEvaluation, get_rule_engine

# 資料資格：飼主端必要欄位 (提案 §四 黃色狀態)
REQUIRED_OWNER_FIELDS: List[Tuple[str, str]] = [
    ("species", "這是貓還是狗？"),
    ("body_weight_kg", "目前體重大約幾公斤？"),
    ("duration_hours", "症狀持續多久了？"),
    ("severity", "嚴重程度如何（次數、是否影響精神與食慾）？"),
    ("current_medications", "目前有沒有正在使用的藥物或保健品？"),
]

# 這些意圖屬政策層攔截，不因資料不足而改判黃色
POLICY_INTENTS = {
    "dosage_request",
    "purchase_request",
    "prescription_request",
    "medication_change_request",
    "diagnosis_request",
    "cross_species_use",
}


# system_action 代碼 → 中文說明（給飼主與獸醫閱讀，非工程用語）
_ACTION_ZH = {
    "halt_product_retrieval": "立即停止產品檢索，改為急診轉介",
    "ask_required_questions": "先提出必要追問，補齊資訊後才繼續",
    "allow_owner_education": "提供經獸醫審核的衛教內容",
    "allow_vet_product_search": "解鎖獸醫專業產品檢索",
    "enforce_role_policy": "依角色權限遮蔽不得顯示的內容",
    "enforce_species_policy": "套用物種限制，避免跨物種誤用",
    "block_expired_sources": "排除已過期或失效的文件來源",
    "refuse_no_evidence": "查無有效來源，拒絕作答",
    "refuse_conflict": "來源存在衝突，拒絕作答並轉介獸醫",
    "deny_role_escalation": "拒絕未經驗證的權限提升",
    "deny_case_access": "拒絕未授權的個案存取",
}

# outcome 代碼 → 中文
_OUTCOME_ZH = {
    "fired": "規則成立",
    "not_fired": "規則未成立",
    "evaluated_missing_data": "資訊不足，無法判定",
}


# 欄位代碼 → 中文（用於說明「缺少什麼資訊」）
_FIELD_ZH = {
    "mentation": "精神狀態", "temperature_c": "體溫", "vomiting": "是否嘔吐",
    "vomit_count_24h": "24 小時嘔吐次數", "can_keep_water": "能否喝水",
    "breathing_effort": "呼吸費力程度", "mucous_membrane_color": "黏膜顏色",
    "human_drug_involved": "是否使用人用藥", "toxin_exposure": "是否接觸毒物",
    "can_urinate": "能否排尿", "duration_hours": "持續時間",
    "body_weight_kg": "體重", "sex": "性別", "age_months": "年齡",
    "severity": "嚴重度", "current_medications": "目前用藥",
}


def _missing_fields_zh(detail: str) -> list[str]:
    """從判定軌跡萃取「缺值」欄位，轉成中文供使用者閱讀。"""
    out: list[str] = []
    for seg in (detail or "").split(";"):
        seg = seg.strip()
        # 兩種缺值表示法：「<field> 缺值」與「<field>=None in [...] -> unknown」
        if "缺值" not in seg and "=None" not in seg:
            continue
        token = seg.split(" ", 1)[0].split("=")[0].strip()
        zh = _FIELD_ZH.get(token)
        if zh and zh not in out:
            out.append(zh)
    return out


def _human_reason(ev: RuleEvaluation) -> tuple[str, list[str]]:
    """把規則判定轉成一句人話，並列出實際命中的症狀描述。

    後端 detail 是機器判定式（供稽核），此處另外產生給人閱讀的說明。
    """
    rule = ev.rule
    facts = getattr(ev, "facts", None) or {}
    symptoms = facts.get("symptoms") or []
    presentations = getattr(rule, "presentations", None) or []
    matched = [s for s in symptoms if s in presentations]

    if ev.outcome == "fired":
        if matched:
            return f"飼主描述中出現「{'、'.join(matched)}」，符合本規則的急症表現。", matched
        return f"本次描述符合「{rule.title}」的判定條件。", matched
    if ev.outcome == "evaluated_missing_data":
        missing = _missing_fields_zh(ev.detail)
        if missing:
            return (
                f"尚未取得{'、'.join(missing)}，無法完全排除這條規則，系統採保守處理。".replace(
                    "取得24", "取得 24"
                ),
                matched,
            )
        return "本次資訊不足以判定這條規則，系統採保守處理。", matched
    return "本次描述不符合這條規則的條件，未觸發。", matched


def _rule_ref(ev: RuleEvaluation) -> RuleRef:
    return RuleRef(
        rule_id=ev.rule.rule_id,
        version=ev.rule.version,
        title=ev.rule.title,
        severity=ev.rule.severity,
        scenario=ev.rule.scenario,
        outcome=ev.outcome,
        detail=ev.detail,
        reason_zh=_human_reason(ev)[0],
        action_zh=(
            _ACTION_ZH.get(getattr(ev.rule, "system_action", ""), "")
            if ev.outcome == "fired"
            else _OUTCOME_ZH.get(ev.outcome, "")
        ),
        owner_message=getattr(ev.rule, "owner_message", "") or "",
        matched_zh=_human_reason(ev)[1],
    )


@dataclass
class GateContext:
    """閘門判定所需的全部輸入。"""

    facts: Dict[str, Any]
    role: Role = Role.OWNER
    vet_verified: bool = False
    owner_authorized: bool = False
    requested_mode: Optional[str] = None
    requires_case_data: bool = False
    claims: List[Claim] = field(default_factory=list)
    candidate_passages: List[SourcePassage] = field(default_factory=list)


@dataclass
class GateDecision:
    state: GateState
    checks: List[CheckResult]
    refusal_reason: RefusalReason
    refusal_detail: str
    fired_rules: List[Rule] = field(default_factory=list)
    required_questions: List[Dict[str, str]] = field(default_factory=list)
    allowed_output_types: List[str] = field(default_factory=list)
    blocked_output_types: List[str] = field(default_factory=list)
    product_retrieval_halted: bool = False
    verification: Optional[VerificationResult] = None
    applicable_scope: Dict[str, Any] = field(default_factory=dict)

    def check(self, check_id: CheckId) -> Optional[CheckResult]:
        for c in self.checks:
            if c.check_id == check_id:
                return c
        return None

    @property
    def all_checks_passed(self) -> bool:
        return all(c.passed for c in self.checks)


class EvidenceGate:
    """推薦資格引擎 — 生成前的確定性判定。"""

    def __init__(
        self,
        rule_engine: Optional[RuleEngine] = None,
        kb: Optional[KnowledgeBase] = None,
        verifier: Optional[ClaimVerifier] = None,
    ):
        self.rules = rule_engine or get_rule_engine()
        self.kb = kb or get_kb()
        self.verifier = verifier or get_verifier()

    # ------------------------------------------------------------------
    # 五項資格檢查
    # ------------------------------------------------------------------
    def check_safety(self, ctx: GateContext) -> CheckResult:
        """1. 安全資格：未觸發需立即處理的紅旗規則。"""
        result = CheckResult(
            check_id=CheckId.SAFETY,
            check_label_zh=CHECK_LABELS_ZH["safety"],
            passed=True,
        )
        evaluations = self.rules.evaluate(ctx.facts, severities=["red"])
        for ev in evaluations:
            if ev.outcome == "fired":
                result.rules_fired.append(_rule_ref(ev))
                result.passed = False
            elif ev.outcome == "evaluated_missing_data":
                # 缺資料無法排除紅旗 → 記為未成立的關鍵規則，交由資料資格處理
                result.rules_failed.append(_rule_ref(ev))

        if not result.passed:
            result.refusal_reason = RefusalReason.EMERGENCY
            result.notes.append(
                f"觸發 {len(result.rules_fired)} 條急症紅旗規則，停止產品檢索。"
            )
        return result

    def check_data(self, ctx: GateContext) -> CheckResult:
        """2. 資料資格：必要資訊已補齊，且沒有關鍵矛盾。"""
        result = CheckResult(
            check_id=CheckId.DATA,
            check_label_zh=CHECK_LABELS_ZH["data"],
            passed=True,
        )
        facts = ctx.facts

        # 獸醫/管理者端不套用飼主必問欄位
        if ctx.role != Role.OWNER:
            result.notes.append("非飼主角色，不套用飼主端必要欄位檢查。")
            return result

        missing: List[str] = []
        for field_name, question in REQUIRED_OWNER_FIELDS:
            value = facts.get(field_name)
            if field_name == "species" and value in (None, "unknown", Species.UNKNOWN.value):
                missing.append(field_name)
            elif value is None or value == "":
                missing.append(field_name)

        if missing:
            result.missing_fields = missing
            lookup = dict(REQUIRED_OWNER_FIELDS)
            result.required_questions = [
                {"field": f, "question": lookup[f]} for f in missing
            ]
            result.passed = False
            result.refusal_reason = RefusalReason.INSUFFICIENT_INFO
            result.notes.append(f"缺少必要欄位: {', '.join(missing)}")

        # 關鍵矛盾檢查
        conflicts = self._detect_contradictions(facts)
        if conflicts:
            result.passed = False
            result.refusal_reason = RefusalReason.INSUFFICIENT_INFO
            result.notes.extend(conflicts)

        # 規則層宣告的必問問題（依情境）
        scenarios = facts.get("scenarios") or []
        for ev in self.rules.evaluate(facts, severities=["yellow"]):
            if ev.rule.scenario in scenarios and ev.outcome != "fired":
                result.rules_failed.append(_rule_ref(ev))

        return result

    @staticmethod
    def _detect_contradictions(facts: Dict[str, Any]) -> List[str]:
        out: List[str] = []
        symptoms = facts.get("symptoms") or []
        if facts.get("can_urinate") is True and "尿不出來" in symptoms:
            out.append("矛盾：同時聲明可排尿與完全無法排尿。")
        if facts.get("mentation") == "normal" and "意識不清" in symptoms:
            out.append("矛盾：精神狀態正常與意識不清同時成立。")
        w = facts.get("body_weight_kg")
        if w is not None and (w <= 0 or w > 120):
            out.append(f"矛盾：體重數值不合理 ({w} kg)。")
        age = facts.get("age_months")
        if age is not None and (age < 0 or age > 360):
            out.append(f"矛盾：年齡數值不合理 ({age} 個月)。")
        return out

    def check_role(self, ctx: GateContext) -> CheckResult:
        """3. 角色資格：輸出內容符合飼主、獸醫或管理者權限。"""
        result = CheckResult(
            check_id=CheckId.ROLE,
            check_label_zh=CHECK_LABELS_ZH["role"],
            passed=True,
        )
        facts = dict(ctx.facts)
        facts.update(
            {
                "role": ctx.role.value,
                "vet_verified": ctx.vet_verified,
                "owner_authorized": ctx.owner_authorized,
                "requested_mode": ctx.requested_mode,
                "requires_case_data": ctx.requires_case_data,
            }
        )

        for ev in self.rules.evaluate(facts, severities=["policy", "role"]):
            if ev.outcome == "fired":
                result.rules_fired.append(_rule_ref(ev))
                result.passed = False

        if not result.passed:
            result.refusal_reason = (
                RefusalReason.ROLE_MISMATCH
                if any(r.severity == "role" for r in result.rules_fired)
                else RefusalReason.POLICY_VIOLATION
            )
            result.notes.append(
                "觸發角色／政策規則: " + ", ".join(r.rule_id for r in result.rules_fired)
            )

        # 要求藍色模式但未通過驗證
        if ctx.requested_mode == "blue":
            if not ctx.vet_verified:
                result.passed = False
                result.refusal_reason = RefusalReason.ROLE_MISMATCH
                result.notes.append("要求藍色模式但未完成獸醫身分驗證。")
            elif ctx.requires_case_data and not ctx.owner_authorized:
                result.passed = False
                result.refusal_reason = RefusalReason.ROLE_MISMATCH
                result.notes.append("獸醫已驗證但缺少飼主授權，不得存取個案資料。")

        return result

    def check_evidence(self, ctx: GateContext) -> CheckResult:
        """4. 證據資格：每項醫療或產品主張都有有效且未過期的來源。

        文件效期一律由系統依日期重算 (見 knowledge.compute_expiry)，
        不採信來源自帶的失效標記 —— 母體中有 1,503 筆過期文件沒有標記。
        """
        result = CheckResult(
            check_id=CheckId.EVIDENCE,
            check_label_zh=CHECK_LABELS_ZH["evidence"],
            passed=True,
        )

        if not ctx.claims:
            result.notes.append("本次無醫療／產品主張需驗證。")
            return result

        # 效期閘門：先排除過期來源
        expired = [p for p in ctx.candidate_passages if p.is_expired]
        unapproved = [
            p for p in ctx.candidate_passages
            if not p.is_expired and p.review_status != "approved"
        ]
        usable = [
            p for p in ctx.candidate_passages
            if not p.is_expired and p.review_status == "approved"
        ]
        if expired:
            result.notes.append(
                f"文件效期閘門排除 {len(expired)} 筆逾效期來源: "
                + ", ".join(p.passage_id for p in expired[:5])
            )
        if unapproved:
            result.notes.append(f"審核狀態閘門排除 {len(unapproved)} 筆未審核來源。")

        verification = self.verifier.verify(ctx.claims, usable)
        result.notes.append(
            f"主張驗證: {len(verification.verified_claims)} 項通過 / "
            f"{len(verification.deleted_claims)} 項無來源"
        )

        if verification.should_refuse or not usable:
            result.passed = False
            result.refusal_reason = RefusalReason.INSUFFICIENT_EVIDENCE
            result.notes.append(
                verification.refusal_detail or "無通過效期閘門的有效來源，依證據資格拒答。"
            )
        elif verification.deleted_claims:
            # 部分主張被刪除但仍有可輸出內容 → 檢查通過，主張已移除
            result.notes.append(verification.refusal_detail)

        return result

    def check_consistency(self, ctx: GateContext, verification: Optional[VerificationResult]) -> CheckResult:
        """5. 一致性資格：來源沒有未解決衝突；否則拒答並轉介。"""
        result = CheckResult(
            check_id=CheckId.CONSISTENCY,
            check_label_zh=CHECK_LABELS_ZH["consistency"],
            passed=True,
        )
        if ctx.facts.get("source_conflict") is True:
            result.passed = False
            result.refusal_reason = RefusalReason.SOURCE_CONFLICT
            result.notes.append("案例明示來源衝突旗標。")
            return result

        conflicts = self._detect_source_conflicts(ctx.candidate_passages)
        if conflicts:
            result.passed = False
            result.refusal_reason = RefusalReason.SOURCE_CONFLICT
            result.notes.extend(conflicts)
        else:
            result.notes.append("來源之間未偵測到未解決衝突。")
        return result

    @staticmethod
    def _detect_source_conflicts(passages: Sequence[SourcePassage]) -> List[str]:
        """同一文件出現多個版本且內容不一致 → 未解決衝突。"""
        by_doc: Dict[str, Dict[str, str]] = {}
        for p in passages:
            if p.is_expired:
                continue
            by_doc.setdefault(p.doc_id, {})[p.version] = p.text
        out: List[str] = []
        for doc_id, versions in by_doc.items():
            if len(versions) > 1:
                texts = set(versions.values())
                if len(texts) > 1:
                    out.append(
                        f"文件 {doc_id} 同時存在 {len(versions)} 個版本且內容不一致: "
                        + ", ".join(sorted(versions.keys()))
                    )
        return out

    # ------------------------------------------------------------------
    # 狀態決策
    # ------------------------------------------------------------------
    def decide(self, ctx: GateContext) -> GateDecision:
        """執行五項檢查並決定四狀態之一。順序即優先序。"""
        checks: List[CheckResult] = []

        # --- 1. 安全資格 (最高優先；紅旗即停) ---
        safety = self.check_safety(ctx)
        checks.append(safety)

        if not safety.passed:
            fired_rules = [
                r for r in (self.rules.get(ref.rule_id) for ref in safety.rules_fired) if r
            ]
            # 紅色狀態仍須完成其餘檢查以填滿護照，但結果不改變狀態
            role = self.check_role(ctx)
            checks.append(role)
            decision = GateDecision(
                state=GateState.RED,
                checks=checks,
                refusal_reason=RefusalReason.EMERGENCY,
                refusal_detail=(
                    "觸發急症紅旗規則 "
                    + ", ".join(r.rule_id for r in fired_rules)
                    + "：停止產品檢索與生成，立即轉介就醫。"
                ),
                fired_rules=fired_rules,
                product_retrieval_halted=True,
            )
            self._apply_policy(decision, ctx, fired_rules)
            decision.applicable_scope = self._scope(ctx, fired_rules)
            return decision

        # --- 3. 角色資格 (政策攔截優先於資料補齊) ---
        role_check = self.check_role(ctx)
        checks.append(role_check)

        if not role_check.passed:
            fired_rules = [
                r for r in (self.rules.get(ref.rule_id) for ref in role_check.rules_fired) if r
            ]
            # 政策攔截：飼主索取劑量/購買/確診 → 仍以綠色狀態提供合規說明與轉介，
            # 但禁止輸出型別已被白名單擋掉；角色升級失敗 → 維持飼主可見範圍。
            state = GateState.GREEN if ctx.role == Role.OWNER else GateState.YELLOW
            decision = GateDecision(
                state=state,
                checks=checks,
                refusal_reason=role_check.refusal_reason,
                refusal_detail=(
                    "; ".join(role_check.notes)
                    or "輸出內容不符合目前角色權限。"
                ),
                fired_rules=fired_rules,
                product_retrieval_halted=True,
            )
            self._apply_policy(decision, ctx, fired_rules)
            decision.applicable_scope = self._scope(ctx, fired_rules)
            return decision

        # --- 2. 資料資格 ---
        data = self.check_data(ctx)
        checks.append(data)

        if not data.passed:
            # 只問固定必要問題
            decision = GateDecision(
                state=GateState.YELLOW,
                checks=checks,
                refusal_reason=RefusalReason.INSUFFICIENT_INFO,
                refusal_detail="; ".join(data.notes) or "必要資訊不足，僅提出必要追問。",
                required_questions=data.required_questions,
                product_retrieval_halted=True,
            )
            self._apply_policy(decision, ctx, [])
            decision.applicable_scope = self._scope(ctx, [])
            return decision

        # --- 4. 證據資格 ---
        evidence = self.check_evidence(ctx)
        checks.append(evidence)

        verification: Optional[VerificationResult] = None
        if ctx.claims:
            usable = [
                p for p in ctx.candidate_passages
                if not p.is_expired and p.review_status == "approved"
            ]
            verification = self.verifier.verify(ctx.claims, usable)

        # --- 5. 一致性資格 ---
        consistency = self.check_consistency(ctx, verification)
        checks.append(consistency)

        if not evidence.passed:
            decision = GateDecision(
                state=GateState.GREEN if ctx.role == Role.OWNER else GateState.BLUE,
                checks=checks,
                refusal_reason=RefusalReason.INSUFFICIENT_EVIDENCE,
                refusal_detail="; ".join(evidence.notes),
                product_retrieval_halted=True,
                verification=verification,
            )
            self._apply_policy(decision, ctx, [])
            decision.applicable_scope = self._scope(ctx, [])
            return decision

        if not consistency.passed:
            decision = GateDecision(
                state=GateState.GREEN if ctx.role == Role.OWNER else GateState.BLUE,
                checks=checks,
                refusal_reason=RefusalReason.SOURCE_CONFLICT,
                refusal_detail="; ".join(consistency.notes),
                product_retrieval_halted=True,
                verification=verification,
            )
            self._apply_policy(decision, ctx, [])
            decision.applicable_scope = self._scope(ctx, [])
            return decision

        # --- 全數通過 ---
        if ctx.role in (Role.VET, Role.ADMIN) and ctx.vet_verified:
            state = GateState.BLUE
            halted = False
        else:
            state = GateState.GREEN
            halted = True  # 飼主端永不進行處方產品檢索

        decision = GateDecision(
            state=state,
            checks=checks,
            refusal_reason=RefusalReason.NONE,
            refusal_detail="",
            product_retrieval_halted=halted,
            verification=verification,
        )
        self._apply_policy(decision, ctx, [])
        decision.applicable_scope = self._scope(ctx, [])
        return decision

    # ------------------------------------------------------------------
    def _apply_policy(
        self, decision: GateDecision, ctx: GateContext, fired_rules: Sequence[Rule]
    ) -> None:
        """把規則宣告的 allowed_outputs 交給角色政策白名單過濾。"""
        requested: List[str] = []
        for r in fired_rules:
            requested.extend(r.allowed_outputs)
        if not requested:
            requested = list(policy.allowed_types_for(ctx.role, decision.state))

        pd = policy.filter_output_types(ctx.role, decision.state, requested)
        decision.allowed_output_types = pd.allowed_output_types

        # 明確記錄被擋下的輸出型別（含規則層宣告的 forbidden_outputs）
        blocked = list(pd.blocked_output_types)
        for r in fired_rules:
            for t in r.forbidden_outputs:
                if t not in blocked:
                    blocked.append(t)
        if ctx.role == Role.OWNER:
            for t in sorted(policy.OWNER_HARD_BANS):
                if t not in blocked:
                    blocked.append(t)
        decision.blocked_output_types = blocked

    @staticmethod
    def _scope(ctx: GateContext, fired_rules: Sequence[Rule]) -> Dict[str, Any]:
        """適用範圍 (提案 §八)。"""
        scope: Dict[str, Any] = {
            "species": ctx.facts.get("species") or "unknown",
            "role": ctx.role.value,
            "scenarios": ctx.facts.get("scenarios") or [],
        }
        if ctx.facts.get("age_months") is not None:
            scope["age_months"] = ctx.facts["age_months"]
        if ctx.facts.get("body_weight_kg") is not None:
            scope["body_weight_kg"] = ctx.facts["body_weight_kg"]
        if fired_rules:
            scope["rule_species_scope"] = sorted(
                {s for r in fired_rules for s in r.species}
            )
            scope["review_status"] = sorted({r.review_status for r in fired_rules})
        return scope


_GATE: Optional[EvidenceGate] = None


def get_gate(reload: bool = False) -> EvidenceGate:
    global _GATE
    if _GATE is None or reload:
        _GATE = EvidenceGate()
    return _GATE
