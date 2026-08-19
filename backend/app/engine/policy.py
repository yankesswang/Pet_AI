"""VetLink AI — 角色政策引擎 (提案 §5.1 / §7.1 角色政策引擎).

以**輸出白名單**實作，而非對模型下指令。任何不在白名單的輸出型別一律移除。
飼主端硬性禁令 (提案 §5.1)：
  - 疾病確診
  - 處方藥劑量
  - 自行停換藥指示
  - 處方藥購買連結
  - 將人用藥直接套用於犬貓
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from ..models import GateState, Role

# --------------------------------------------------------------------------
# 白名單：角色 × 狀態 → 允許的輸出型別
# --------------------------------------------------------------------------
OWNER_BASE_ALLOWED: Set[str] = {
    "triage_explanation",
    "emergency_referral",
    "danger_signs",
    "first_aid_cooling",
    "required_questions",
    "interim_safety_notice",
    "education",
    "observation_checklist",
    "visit_summary",
    "policy_explanation",
    "vet_referral",
    "refusal_reason",
    "species_warning",
    "human_drug_warning",
    "poison_info_intake",
    "conflict_disclosure",
    "product_category_discussion",  # 僅類別，不含處方決策
    "vet_verification_instruction",
    "authorization_request",
}

VET_BASE_ALLOWED: Set[str] = OWNER_BASE_ALLOWED | {
    "approved_indications",
    "ingredients",
    "dosage_form",
    "label_text",
    "product_comparison",
    "product_recommendation",
    "case_summary",
    "regulatory_class",
}

ADMIN_BASE_ALLOWED: Set[str] = VET_BASE_ALLOWED | {
    "document_versions",
    "audit_records",
    "impact_replay_report",
}

ROLE_ALLOWLIST: Dict[Role, Set[str]] = {
    Role.OWNER: OWNER_BASE_ALLOWED,
    Role.VET: VET_BASE_ALLOWED,
    Role.ADMIN: ADMIN_BASE_ALLOWED,
}

# 各狀態進一步收斂的白名單（與角色白名單取交集）
STATE_ALLOWLIST: Dict[GateState, Set[str]] = {
    GateState.RED: {
        "triage_explanation",
        "emergency_referral",
        "danger_signs",
        "first_aid_cooling",
        "visit_summary",
        "policy_explanation",
        "refusal_reason",
        "human_drug_warning",
        "species_warning",
        "poison_info_intake",
        "vet_referral",
    },
    GateState.YELLOW: {
        "required_questions",
        "interim_safety_notice",
        "danger_signs",
        "policy_explanation",
        "refusal_reason",
        "vet_referral",
        "species_warning",
    },
    GateState.GREEN: {
        "education",
        "observation_checklist",
        "danger_signs",
        "visit_summary",
        "policy_explanation",
        "vet_referral",
        "refusal_reason",
        "product_category_discussion",
        "triage_explanation",
        "conflict_disclosure",
        "vet_verification_instruction",
        "species_warning",
        "human_drug_warning",
    },
    GateState.BLUE: {
        "approved_indications",
        "ingredients",
        "dosage_form",
        "label_text",
        "product_comparison",
        "product_recommendation",
        "case_summary",
        "regulatory_class",
        "refusal_reason",
        "policy_explanation",
        "document_versions",
        "danger_signs",
        "visit_summary",
    },
}

# 飼主端絕對禁止的輸出型別 (硬性禁令，任何狀態皆不可覆寫)
OWNER_HARD_BANS: Set[str] = {
    "diagnosis",
    "dosage",
    "prescription_dosage",
    "owner_facing_dosage",
    "home_medication",
    "medication_change_instruction",
    "purchase_link",
    "prescription_product",
    "human_drug_dosing",
    "cross_species_dosing",
    "induce_vomiting_instruction",
}

# --------------------------------------------------------------------------
# 文字層防線：偵測已生成文字中的違規內容
# --------------------------------------------------------------------------
DOSAGE_PATTERNS: List[re.Pattern] = [
    re.compile(r"\d+(?:\.\d+)?\s*(?:mg|MG|毫克|公絲)\s*/\s*(?:kg|KG|公斤)"),
    re.compile(r"每\s*(?:公斤|kg)\s*\d+(?:\.\d+)?\s*(?:mg|毫克|ml|毫升)"),
    re.compile(r"(?:一天|每天|每日)\s*(?:吃|餵|給|服用)?\s*\d+(?:\.\d+)?\s*(?:顆|錠|粒|次|ml|毫升|mg|毫克)"),
    re.compile(r"\d+(?:\.\d+)?\s*(?:顆|錠|粒)\s*(?:，|,)?\s*(?:一天|每天|每日|每\s*\d+\s*小時)"),
    re.compile(r"(?:服用|口服|投與|投藥)\s*\d+(?:\.\d+)?\s*(?:mg|毫克|ml|毫升|顆|錠)"),
    re.compile(r"每\s*\d+\s*小時\s*(?:一次|投與|給藥|餵)"),
]

PURCHASE_PATTERNS: List[re.Pattern] = [
    re.compile(r"https?://\S*(?:shopee|momo|pchome|ruten|amazon|買|shop|store|cart)", re.I),
    re.compile(r"(?:可至|可到|請至|前往)\S{0,12}(?:蝦皮|momo|PChome|露天|網購|電商)\S{0,12}(?:購買|下單)"),
    re.compile(r"(?:購買連結|下單連結|加入購物車)"),
]

DIAGNOSIS_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?:確定|確診|就是|可以判定|診斷為)(?:是)?\s*\S{0,10}(?:症|炎|病|癌|阻塞|感染|結石)"),
    re.compile(r"牠(?:得了|罹患|患有)"),
]

MED_CHANGE_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?:可以|建議|請)\s*(?:先)?\s*(?:自行)?\s*(?:停藥|停止服用|停掉|減量|換成|改用)\S{0,8}(?:藥|錠|劑)"),
    re.compile(r"(?:自行)\s*(?:停藥|換藥|調整劑量)"),
]

HUMAN_DRUG_APPLY_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?:可以|建議|不妨)\s*(?:給|餵|使用)\S{0,6}(?:普拿疼|乙醯胺酚|布洛芬|阿斯匹靈|人用感冒藥|人的止痛藥)"),
    re.compile(r"(?:普拿疼|乙醯胺酚|布洛芬|阿斯匹靈)\S{0,10}(?:可以給|適用於|可用於)\S{0,4}(?:貓|狗|犬|寵物)"),
]

# 白名單允許的「反向警告」語句：明確禁止時不算洩漏
NEGATION_GUARDS = [
    "不可", "不得", "切勿", "請勿", "禁止", "無法提供", "不提供", "不會提供",
    "具毒性", "有毒", "可能致命", "不建議", "勿自行", "須由獸醫",
]


@dataclass
class PolicyDecision:
    allowed_output_types: List[str] = field(default_factory=list)
    blocked_output_types: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.violations


def allowed_types_for(role: Role, state: GateState) -> Set[str]:
    """角色白名單 ∩ 狀態白名單，再扣除飼主硬性禁令。"""
    allowed = ROLE_ALLOWLIST.get(role, set()) & STATE_ALLOWLIST.get(state, set())
    if role == Role.OWNER:
        allowed = allowed - OWNER_HARD_BANS
    return allowed


def filter_output_types(
    role: Role, state: GateState, requested: List[str]
) -> PolicyDecision:
    """對規則宣告的 allowed_outputs 施加白名單過濾。"""
    allowed_set = allowed_types_for(role, state)
    decision = PolicyDecision()
    for t in requested:
        if t in allowed_set:
            if t not in decision.allowed_output_types:
                decision.allowed_output_types.append(t)
        else:
            if t not in decision.blocked_output_types:
                decision.blocked_output_types.append(t)
            if role == Role.OWNER and t in OWNER_HARD_BANS:
                decision.violations.append(f"飼主端硬性禁令輸出型別遭要求: {t}")
    return decision


def _has_negation_guard(text: str, span_start: int) -> bool:
    """檢查違規片段附近是否為明確的禁止／警告語境。"""
    window = text[max(0, span_start - 40): span_start + 40]
    return any(g in window for g in NEGATION_GUARDS)


def scan_text_for_violations(role: Role, text: str) -> List[str]:
    """文字層最終防線 — 掃描已生成內容中的角色違規。

    僅對飼主 (OWNER) 施加處方劑量/購買/確診/停換藥/人藥套用的禁令。
    """
    if role != Role.OWNER or not text:
        return []

    violations: List[str] = []
    checks: List[Tuple[str, List[re.Pattern]]] = [
        ("處方藥劑量洩漏", DOSAGE_PATTERNS),
        ("處方藥購買連結", PURCHASE_PATTERNS),
        ("疾病確診", DIAGNOSIS_PATTERNS),
        ("自行停換藥指示", MED_CHANGE_PATTERNS),
        ("人用藥套用於犬貓", HUMAN_DRUG_APPLY_PATTERNS),
    ]
    for label, patterns in checks:
        for pat in patterns:
            for m in pat.finditer(text):
                if _has_negation_guard(text, m.start()):
                    continue
                violations.append(f"{label}: 「{m.group(0)}」")
                break
    return violations


def enforce(role: Role, state: GateState, requested_types: List[str], texts: List[str]) -> PolicyDecision:
    """完整政策執行：型別白名單 + 文字掃描。"""
    decision = filter_output_types(role, state, requested_types)
    for t in texts:
        decision.violations.extend(scan_text_for_violations(role, t))
    return decision


def redact(role: Role, text: str) -> Tuple[str, List[str]]:
    """若文字含違規內容，刪除該句並回報。對應提案『失敗即刪除或拒答』。"""
    violations = scan_text_for_violations(role, text)
    if not violations:
        return text, []
    sentences = re.split(r"(?<=[。！？\n])", text)
    kept = [s for s in sentences if not scan_text_for_violations(role, s)]
    return "".join(kept).strip(), violations
