"""VetLink AI — 共用資料模型 (Pydantic v2).

對應提案 §四 (四種狀態)、§五 (三種角色)、§八 (回答護照)。
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# 列舉
# --------------------------------------------------------------------------
class GateState(str, Enum):
    """提案 §四：四種狀態。"""

    RED = "RED"        # 不得推薦
    YELLOW = "YELLOW"  # 資訊不足
    GREEN = "GREEN"    # 飼主可見
    BLUE = "BLUE"      # 獸醫專業模式


STATE_LABELS_ZH: Dict[str, str] = {
    "RED": "紅色｜不得推薦",
    "YELLOW": "黃色｜資訊不足",
    "GREEN": "綠色｜飼主可見",
    "BLUE": "藍色｜獸醫專業模式",
}


class Role(str, Enum):
    """提案 §五：三種角色。"""

    OWNER = "owner"    # 飼主
    VET = "vet"        # 獸醫
    ADMIN = "admin"    # 中化管理者


class Species(str, Enum):
    CAT = "cat"
    DOG = "dog"
    UNKNOWN = "unknown"


class BodySize(str, Enum):
    """犬體型分級 (提案 §5.1)。

    體型是**臨床風險分層**的依據，與體重公斤數用途不同：
    公斤數是算劑量用的，但本系統依政策層規定不輸出劑量，
    因此公斤數本身無法改變任何判定；真正影響風險的是體型 ——
    胃扭轉好發於大型深胸犬種、氣管塌陷好發於小型犬，
    同樣的主訴在不同體型上代表不同的急迫性。

    貓的體型差異在臨床上遠不如犬顯著，故本欄位僅適用於犬。
    """

    SMALL = "small"      # 小型犬，約 10 公斤以下
    MEDIUM = "medium"    # 中型犬，約 10–25 公斤
    LARGE = "large"      # 大型犬，約 25 公斤以上
    UNKNOWN = "unknown"


class Mentation(str, Enum):
    NORMAL = "normal"
    LETHARGIC = "lethargic"
    COLLAPSED = "collapsed"
    UNKNOWN = "unknown"


class Intent(str, Enum):
    """使用者意圖 — 由確定性關鍵字比對得出，不經 LLM。"""

    GENERAL = "general"
    EDUCATION = "education"
    DOSAGE_REQUEST = "dosage_request"
    PURCHASE_REQUEST = "purchase_request"
    PRESCRIPTION_REQUEST = "prescription_request"
    MEDICATION_CHANGE_REQUEST = "medication_change_request"
    DIAGNOSIS_REQUEST = "diagnosis_request"
    CROSS_SPECIES_USE = "cross_species_use"


class CheckId(str, Enum):
    """提案 §四：五項資格檢查。"""

    SAFETY = "safety"            # 安全資格
    DATA = "data"                # 資料資格
    ROLE = "role"                # 角色資格
    EVIDENCE = "evidence"        # 證據資格
    CONSISTENCY = "consistency"  # 一致性資格


CHECK_LABELS_ZH: Dict[str, str] = {
    "safety": "安全資格",
    "data": "資料資格",
    "role": "角色資格",
    "evidence": "證據資格",
    "consistency": "一致性資格",
}


class RefusalReason(str, Enum):
    """提案 §八：拒絕原因。"""

    NONE = "none"
    INSUFFICIENT_INFO = "insufficient_info"      # 資訊不足
    EMERGENCY = "emergency"                      # 急症
    ROLE_MISMATCH = "role_mismatch"              # 角色不符
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # 證據不足
    SOURCE_CONFLICT = "source_conflict"          # 來源衝突
    POLICY_VIOLATION = "policy_violation"        # 政策禁止


# --------------------------------------------------------------------------
# 輸入
# --------------------------------------------------------------------------
class ConsultRequest(BaseModel):
    """飼主端症狀輸入 (提案 §5.1)。"""

    text: str = Field(default="", description="飼主自然語言描述")
    role: Role = Role.OWNER
    species: Optional[Species] = None
    # 體型：臨床風險分層用（小／中／大型犬）。未提供時由體重推導。
    body_size: Optional[BodySize] = None
    # 體重：僅作合理性檢查與體型推導；本系統不輸出劑量，故不再列為必答。
    body_weight_kg: Optional[float] = None
    age_months: Optional[int] = None
    sex: Optional[str] = None
    duration_hours: Optional[float] = None
    severity: Optional[str] = None
    current_medications: Optional[List[str]] = None
    can_urinate: Optional[bool] = None
    vomiting: Optional[bool] = None
    mentation: Optional[Mentation] = None
    breathing_effort: Optional[str] = None
    mucous_membrane_color: Optional[str] = None
    temperature_c: Optional[float] = None
    vomit_count_24h: Optional[int] = None
    can_keep_water: Optional[bool] = None
    session_id: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class VetSearchRequest(BaseModel):
    """藍色模式產品檢索 (提案 §5.2)。"""

    query: str = ""
    species: Optional[Species] = None
    indication: Optional[str] = None
    ingredient: Optional[str] = None
    dosage_form: Optional[str] = None
    case_audit_id: Optional[str] = None
    limit: int = 10

    # 飼主授權**不接受呼叫端自我宣告**。
    #
    # 這個欄位原本是 `owner_authorized: bool = True`，也就是預設已授權，
    # 而且由 request body 傳入 —— 任何呼叫端都能自稱「飼主已授權」。
    # 那是流程示意，不是可驗證的授權鏈。
    #
    # 現在改為提交一張由伺服器簽章、有時效、綁定個案的授權憑證 (grant)。
    # 授權與否一律由伺服器驗章後決定，見 `app.engine.authz`。
    grant_token: Optional[str] = Field(
        default=None,
        description="飼主授權憑證（QR Code 內容）。缺少或驗證失敗即視為未授權。",
    )


# --------------------------------------------------------------------------
# 規則與檢查結果
# --------------------------------------------------------------------------
class RuleRef(BaseModel):
    """觸發／未觸發規則的引用 (提案 §八：觸發規則)。"""

    rule_id: str
    version: str
    title: str
    severity: str
    scenario: str
    outcome: str  # fired | not_fired | evaluated_missing_data
    detail: str = ""  # 機器判定式，供稽核與除錯
    # 以下為給飼主／獸醫閱讀的自然語言說明（提案 §八：觸發規則需人類可讀）
    reason_zh: str = ""  # 這條規則為何成立／未成立
    action_zh: str = ""  # 規則成立後系統做了什麼
    owner_message: str = ""  # 獸醫審核過的飼主說明
    matched_zh: List[str] = Field(default_factory=list)  # 實際命中的症狀描述


class CheckResult(BaseModel):
    """單一資格檢查的結構化結果。"""

    check_id: CheckId
    check_label_zh: str
    passed: bool
    rules_fired: List[RuleRef] = Field(default_factory=list)
    rules_failed: List[RuleRef] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    required_questions: List[Dict[str, str]] = Field(default_factory=list)
    refusal_reason: RefusalReason = RefusalReason.NONE
    notes: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 證據與主張
# --------------------------------------------------------------------------
class SourcePassage(BaseModel):
    """來源段落 — 主張級引用的最小單位 (提案 §八)。"""

    passage_id: str
    doc_id: str
    version: str
    text: str
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    source_org: Optional[str] = None
    source_type: str = "internal"  # online | internal | government_open_data
    issue_date_iso: Optional[str] = None
    expiry_date_iso: Optional[str] = None
    is_expired: bool = False
    review_status: str = "approved"
    species_scope: List[str] = Field(default_factory=list)
    # 適用情境（泌尿／腸胃／皮膚耳部／呼吸／跨情境）。這是明確標註的資料，
    # 用來取代關鍵字計分檢索 —— 「食慾」「飲水」這類通用詞會把不相關情境的
    # 段落帶進候選，段落本身雖然仍有來源支持，但對這次提問並不切題。
    scenario_scope: List[str] = Field(default_factory=list)
    licence_no: Optional[str] = None
    fetched_at: Optional[str] = None


class Claim(BaseModel):
    """一項醫療或產品主張。"""

    claim_id: str
    text: str
    claim_type: str = "medical"  # medical | product | educational | procedural
    supporting_passage_ids: List[str] = Field(default_factory=list)
    verified: bool = False
    verification_note: str = ""


class ClaimBinding(BaseModel):
    """回答護照中的主張→來源綁定 (claim-level, 非 document-level)。"""

    claim_id: str
    claim_text: str
    claim_type: str
    supported: bool
    passages: List[SourcePassage] = Field(default_factory=list)
    note: str = ""


# --------------------------------------------------------------------------
# 回答護照 (提案 §八)
# --------------------------------------------------------------------------
class DocumentVersionRef(BaseModel):
    doc_id: str
    version: str
    issue_date_iso: Optional[str] = None
    expiry_date_iso: Optional[str] = None
    last_reviewed_at: Optional[str] = None
    is_expired: bool = False


class AnswerPassport(BaseModel):
    """提案 §八 回答護照 — 八個必要欄位皆為必填。"""

    audit_id: str                                   # 稽核編號
    answer_state: GateState                         # 回答狀態
    answer_state_label_zh: str                      # 中文狀態標籤
    applicable_role: Role                           # 適用角色
    rules_fired: List[RuleRef] = Field(default_factory=list)     # 觸發規則（成立）
    rules_failed: List[RuleRef] = Field(default_factory=list)    # 觸發規則（未成立）
    claim_bindings: List[ClaimBinding] = Field(default_factory=list)  # 支持來源（主張級）
    document_versions: List[DocumentVersionRef] = Field(default_factory=list)  # 文件版本
    applicable_scope: Dict[str, Any] = Field(default_factory=dict)  # 適用範圍
    refusal_reason: RefusalReason = RefusalReason.NONE            # 拒絕原因
    refusal_detail: str = ""
    checks: List[CheckResult] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    engine_version: str = "1.0.0"
    rules_bundle_version: str = ""

    def required_fields_complete(self) -> bool:
        """提案 §12.1「回答具完整稽核紀錄 100%」的判定依據。"""
        if not self.audit_id or not self.answer_state_label_zh:
            return False
        if not self.rules_fired and not self.rules_failed:
            return False
        if not self.applicable_scope:
            return False
        if not self.rules_bundle_version:
            return False
        # 非拒答狀態必須有主張綁定；拒答狀態必須有拒絕原因
        if self.refusal_reason == RefusalReason.NONE:
            return bool(self.claim_bindings)
        return bool(self.refusal_detail)


# --------------------------------------------------------------------------
# 回應
# --------------------------------------------------------------------------
class ConsultResponse(BaseModel):
    audit_id: str
    state: GateState
    state_label_zh: str
    headline: str
    messages: List[str] = Field(default_factory=list)
    required_questions: List[Dict[str, str]] = Field(default_factory=list)
    danger_signs: List[str] = Field(default_factory=list)
    allowed_output_types: List[str] = Field(default_factory=list)
    blocked_output_types: List[str] = Field(default_factory=list)
    product_retrieval_halted: bool = False
    visit_summary: Optional[Dict[str, Any]] = None
    # 衛教語言轉譯的稽核摘要：這次有幾段實際被 LLM 改寫、幾段退回原文。
    # 轉譯旗標關閉（預設）時每一段都是 fallback，rewritten_count 恆為 0。
    llm_translation: Optional[Dict[str, Any]] = None
    # 檢索軌跡：文件庫 → 候選 → 主張 → 實際輸出的四層漏斗，含被排除段落與原因。
    # 讓「系統只講有來源的話」可被當場檢查，而不只是一句宣稱。
    retrieval: Optional[Dict[str, Any]] = None
    passport: AnswerPassport


class ProductCard(BaseModel):
    licence_no: str
    name_zh: str
    name_en: Optional[str] = None
    company: Optional[str] = None
    dosage_form: Optional[str] = None
    packaging: Optional[str] = None
    ingredients_clean: Optional[str] = None
    indications_raw: Optional[str] = None
    species: List[str] = Field(default_factory=list)
    is_companion_animal: bool = True
    issue_date_iso: Optional[str] = None
    expiry_date_iso: Optional[str] = None
    is_expired: bool = False
    doc_id: str = ""
    version: str = "1.0"
    source_url: Optional[str] = None
    fetched_at: Optional[str] = None
    # 效期閘門稽核欄位
    expiry_unknown: bool = False
    expiry_date_raw: Optional[str] = None
    expired_by_marker: bool = False


class VetSearchResponse(BaseModel):
    audit_id: str
    state: GateState
    state_label_zh: str
    results: List[ProductCard] = Field(default_factory=list)
    excluded_expired_count: int = 0
    excluded_expired_licences: List[str] = Field(default_factory=list)
    passport: AnswerPassport
