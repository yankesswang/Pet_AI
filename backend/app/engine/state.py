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
    ("body_size", "體型大約是？（小型犬約10公斤以下／中型犬10-25公斤／大型犬25公斤以上）"),
    ("duration_hours", "症狀持續多久了？"),
    ("severity", "嚴重程度如何（次數、是否影響精神與食慾）？"),
    ("current_medications", "目前有沒有正在使用的藥物或保健品？"),
]

# 索取劑量／購買／確診等意圖屬政策層攔截，不因資料不足而改判黃色去追問。
# 這件事**由檢查順序保證**：`decide()` 先跑角色資格（severity: policy／role）
# 才跑資料資格，政策規則一旦成立就直接回傳，走不到黃色分支。
# 涵蓋這些意圖的規則：VG-POL-420（劑量／購買／處方）、VG-POL-421（停換藥）、
# VG-POL-422（確診）、VG-POL-430（跨物種）、VG-POL-431（物種未指明）。
#
# 註：此處原本另有一份 POLICY_INTENTS 意圖清單，但全專案從未被引用 ——
# 它看起來像在控制流程，實際上沒有。已移除，避免誤導後續維護者。


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
    "body_size": "體型", "body_weight_kg": "體重", "sex": "性別", "age_months": "年齡",
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

        # --- 理解資格 (fail-closed) ---------------------------------
        # 留出集揭露的核心缺陷：詞典比對不到任何症狀時，系統會一路落到綠色，
        # 把「我看不懂這句話」當成「這個案例沒有危險」。這兩件事完全不同。
        #
        # 因此只要飼主明確在描述身體狀況、但正規化後抽不出任何可判定的臨床
        # 訊號，一律停在黃色追問，**絕不直接給綠色衛教**。寧可多問一次，
        # 也不要對看不懂的急症說「在家觀察就好」。
        comprehension = self._check_comprehension(facts)
        if comprehension:
            result.passed = False
            result.refusal_reason = RefusalReason.INSUFFICIENT_INFO
            result.notes.append(comprehension)
            result.missing_fields = list(
                dict.fromkeys(result.missing_fields + ["symptoms"])
            )
            result.required_questions = result.required_questions + [
                {
                    "field": "symptoms",
                    "question": (
                        "可以更具體描述目前的狀況嗎？例如：呼吸、排尿排便、"
                        "嘔吐、精神食慾，以及是什麼時候開始的。"
                    ),
                }
            ]

        missing: List[str] = []
        species_val = facts.get("species")
        for field_name, question in REQUIRED_OWNER_FIELDS:
            value = facts.get(field_name)
            if field_name == "species" and value in (None, "unknown", Species.UNKNOWN.value):
                missing.append(field_name)
                continue
            # 體型分級只適用於犬。對貓追問「小型犬還是大型犬」不僅無意義，
            # 還會讓貓的案例永遠補不齊必要欄位而卡在黃色。
            # 物種未知時也不問 —— 先問出物種，下一輪才知道該不該問體型。
            if field_name == "body_size" and species_val != Species.DOG.value:
                continue
            if value is None or value == "":
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

    # 表示「我家動物現在有狀況」的訊號。純衛教提問（「想知道中暑前兆」）
    # 不含這些詞，因此不會被 fail-closed 攔下來 —— 那類問題本來就該給綠色。
    _COMPLAINT_CUES = (
        "怪怪", "不舒服", "不對勁", "生病", "怎麼辦", "怎麼半", "怎辦",
        "看起來", "好像", "一直", "突然", "剛剛", "現在", "今天", "昨天",
        "從半夜", "從早上", "越來越", "有點", "很痛", "在痛", "沒精神",
        "不吃", "不喝", "沒食慾", "救", "急",
    )

    @classmethod
    def _check_comprehension(cls, facts: Dict[str, Any]) -> str:
        """fail-closed：抽不出臨床訊號但明顯在求助 → 回傳原因字串。

        回傳空字串代表理解資格通過。
        """
        if facts.get("symptoms"):
            return ""
        # 這些欄位任一有值，代表仍有可判定的臨床訊號，不算「看不懂」。
        #
        # 刻意**不含** severity：那是飼主自評的嚴重度，不是臨床徵象。
        # 「貓咪不舒服」配上 severity=mild 仍然沒有說出哪裡不對勁，
        # 拿它當作理解成立會讓 fail-closed 形同虛設。
        for key in (
            "toxin_exposure", "human_drug_involved", "can_urinate", "vomiting",
            "mentation", "breathing_effort", "mucous_membrane_color",
            "temperature_c", "vomit_count_24h", "can_keep_water",
        ):
            if facts.get(key) not in (None, "", "unknown"):
                return ""
        # 政策意圖（索取劑量／購買／確診…）由角色資格處理，不在此攔截。
        if facts.get("intent") not in (None, "", "general"):
            return ""

        raw = (facts.get("normalized_text") or facts.get("raw_text") or "").strip()
        if not raw:
            return "未取得任何描述，無法判定安全性。"

        filtered = facts.get("symptoms_by_assertion") or {}
        if any(k != "present" for k in filtered):
            # 命中了症狀但全部落在否定／過去／假設／第三方語境。
            # 這是**有意義的判定**（例如衛教提問），不是看不懂，放行。
            return ""

        if any(cue in raw for cue in cls._COMPLAINT_CUES):
            return (
                "描述中提到身體狀況，但系統無法從中辨識出可判定的臨床徵象；"
                "依 fail-closed 原則不提供衛教結論，改為追問。"
            )
        return ""

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

        # 把上面的判定同時以規則形式記錄下來。
        # VG-EVD-440/441/442 三條規則原本從未被評估（沒有任何地方跑
        # severities=["evidence"]），導致因證據不足而拒答的回答，護照裡
        # 找不到任何規則編號 —— 「哪一條規則讓系統拒答」無從回查。
        # 規則不改變上面的 passed 判定，只補齊稽核軌跡與飼主說明。
        for ev in self.rules.evaluate(self._evidence_facts(ctx, expired, verification),
                                      severities=["evidence"]):
            if ev.outcome == "fired":
                result.rules_fired.append(_rule_ref(ev))

        return result

    def _evidence_facts(
        self,
        ctx: GateContext,
        expired: Sequence[SourcePassage],
        verification: VerificationResult,
    ) -> Dict[str, Any]:
        """VG-EVD-* 規則需要的欄位。全部明確給值，避免規則落入 unknown。"""
        supporting = {
            p.passage_id
            for b in verification.bindings if b.supported
            for p in b.passages
        }
        facts = dict(ctx.facts)
        facts.update(
            {
                "source_expired": bool(expired),
                "supporting_sources_count": len(supporting),
                "source_conflict": bool(ctx.facts.get("source_conflict"))
                or bool(self._detect_source_conflicts(ctx.candidate_passages)),
            }
        )
        return facts

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

            # 但若規則自己宣告的動作就是「先追問」（例如 VG-POL-431 物種未指明），
            # 綠色會與規則意圖直接矛盾 —— 規則只允許輸出 required_questions，
            # 系統卻回一則衛教結論。這類規則一律走黃色追問。
            asking_rules = [
                r for r in fired_rules
                if getattr(r, "system_action", "") == "ask_required_questions"
            ]
            required_questions: List[Dict[str, str]] = []
            if asking_rules:
                state = GateState.YELLOW
                seen: set[str] = set()
                for r in asking_rules:
                    for q in (getattr(r, "required_questions", None) or []):
                        field_name = q.get("field") if isinstance(q, dict) else None
                        question = q.get("question") if isinstance(q, dict) else None
                        if question and field_name not in seen:
                            seen.add(field_name)
                            required_questions.append(
                                {"field": field_name or "", "question": question}
                            )

            decision = GateDecision(
                state=state,
                checks=checks,
                refusal_reason=role_check.refusal_reason,
                refusal_detail=(
                    "; ".join(role_check.notes)
                    or "輸出內容不符合目前角色權限。"
                ),
                fired_rules=fired_rules,
                required_questions=required_questions,
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
            evidence_rules = [
                r for r in (self.rules.get(ref.rule_id) for ref in evidence.rules_fired) if r
            ]
            decision = GateDecision(
                state=GateState.GREEN if ctx.role == Role.OWNER else GateState.BLUE,
                checks=checks,
                refusal_reason=RefusalReason.INSUFFICIENT_EVIDENCE,
                refusal_detail="; ".join(evidence.notes),
                fired_rules=evidence_rules,
                product_retrieval_halted=True,
                verification=verification,
            )
            # 輸出白名單仍取自角色×狀態，不縮到規則宣告的範圍：
            # VG-EVD-* 的 allowed_outputs 不含 visit_summary，若改用它會讓
            # 飼主在拒答時連就診摘要都拿不到 —— 那是拒答時最該給的東西。
            # 規則在此只負責提供可回查的編號與已審核的拒答說明。
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
        if ctx.facts.get("body_size") is not None:
            scope["body_size"] = ctx.facts["body_size"]
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
