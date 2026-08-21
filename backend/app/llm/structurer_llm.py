"""VetLink AI — LLM 輔助症狀結構化器 (提案 §7.1「部分；需 Schema 驗證」).

這是提案允許 LLM 介入的第一處，也是唯一會影響閘門輸入的一處。因此其邊界必須
極為明確：

    自然語言 → [LLM 抽取] → Pydantic Schema 驗證 → 與詞典結果合併 → facts
                                                                      ↓
                                                          Evidence Gate（確定性）

**LLM 不判定任何狀態。** 它只把「貓」「尿不出來」這類描述轉成欄位值。
所有紅旗規則、資格檢查、主張驗證仍在合併後的 facts 上以確定性方式執行。

合併規則（安全優先）：
  1. **詞典命中一律保留**。LLM 不得刪除既有症狀或欄位值。
  2. LLM 只能**新增**詞典漏抽的症狀（且必須是既有詞典的正規名稱，
     避免模型自創症狀名而繞過規則比對）。
  3. 對「紅旗相關欄位」發生衝突時，**一律取較保守（較危險）的值**。
     例：詞典判 can_urinate=False、LLM 判 True → 取 False。
  4. 任何驗證失敗、欄位型別錯誤或值不在列舉內 → 整份 LLM 結果作廢，
     退回純詞典結果。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..engine.structurer import SYMPTOM_LEXICON, structure_case
from ..models import BodySize, ConsultRequest, Mentation, Species
from .client import LLMClient, get_client, structuring_enabled

log = logging.getLogger("vetlink.llm.structurer")

# 詞典正規症狀名 —— LLM 只能從這裡面選，不得自創
CANONICAL_SYMPTOMS = set(SYMPTOM_LEXICON.keys())

# 紅旗相關欄位：這些欄位一旦衝突，一律取「較危險」的值
# 值為該欄位的「危險方向」判定函式所需的設定
SAFER_BOOL_FALSE = {"can_urinate", "can_keep_water"}   # False 較危險
SAFER_BOOL_TRUE = {"vomiting", "human_drug_involved", "toxin_exposure"}  # True 較危險

# mentation 的危險程度排序（越後面越危險）
MENTATION_SEVERITY = {
    "normal": 0,
    "unknown": 1,
    "lethargic": 2,
    "collapsed": 3,
}


# --------------------------------------------------------------------------
# LLM 輸出 Schema —— 這是「受控生成」的契約
# --------------------------------------------------------------------------
class LLMStructuredSymptoms(BaseModel):
    """LLM 症狀抽取結果的嚴格 schema。

    欄位刻意全部 Optional：模型不確定時應留空，而不是猜測。
    任何不符此 schema 的輸出都會讓整份結果作廢。
    """

    model_config = {"extra": "forbid"}

    species: Optional[Species] = None
    symptoms: List[str] = Field(default_factory=list)
    body_weight_kg: Optional[float] = None
    body_size: Optional[BodySize] = None
    age_months: Optional[int] = None
    sex: Optional[str] = None
    duration_hours: Optional[float] = None
    mentation: Optional[Mentation] = None
    can_urinate: Optional[bool] = None
    vomiting: Optional[bool] = None
    can_keep_water: Optional[bool] = None
    temperature_c: Optional[float] = None
    human_drug_involved: Optional[bool] = None
    toxin_exposure: Optional[bool] = None

    @field_validator("symptoms")
    @classmethod
    def _only_canonical(cls, v: List[str]) -> List[str]:
        """模型只能使用詞典既有的正規症狀名。

        若混入自創名稱，直接丟棄該項 —— 因為規則引擎只認得詞典名稱，
        放行自創名稱等於讓模型有機會繞過規則比對。
        """
        return [s for s in v if s in CANONICAL_SYMPTOMS]

    @field_validator("body_weight_kg")
    @classmethod
    def _sane_weight(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not (0.05 <= v <= 120.0):
            raise ValueError("body_weight_kg 超出犬貓合理範圍")
        return v

    @field_validator("age_months")
    @classmethod
    def _sane_age(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if not (0 <= v <= 360):
            raise ValueError("age_months 超出合理範圍")
        return v

    @field_validator("duration_hours")
    @classmethod
    def _sane_duration(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not (0 <= v <= 24 * 365):
            raise ValueError("duration_hours 超出合理範圍")
        return v

    @field_validator("temperature_c")
    @classmethod
    def _sane_temp(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not (25.0 <= v <= 45.0):
            raise ValueError("temperature_c 超出合理範圍")
        return v


SYSTEM_PROMPT = """你是動物用藥系統的「症狀結構化器」。你的唯一工作是把飼主的中文口語描述，抽取成結構化欄位。

嚴格規則：
1. 你**不做任何醫療判斷**：不判斷是否為急症、不判斷嚴重度、不建議任何藥物或處置。
2. symptoms 欄位只能從下列允許清單中選取，**不得自創名稱**，不得翻譯或改寫：
{symptom_list}
3. 飼主沒有明確提到的資訊，一律留 null 或空陣列。**絕對不要推測或補齊**。
4. species 只能是 "cat"、"dog" 或 null。mentation 只能是 "normal"、"lethargic"、"collapsed" 或 null。
5. can_urinate：飼主明確表示排得出尿才填 true；明確表示尿不出來填 false；未提及填 null。
6. 只輸出 JSON 物件，不要任何說明文字。

輸出 JSON 欄位：species, symptoms, body_weight_kg, body_size, age_months, sex, duration_hours,
mentation, can_urinate, vomiting, can_keep_water, temperature_c, human_drug_involved, toxin_exposure
"""


def _build_system_prompt() -> str:
    names = "、".join(sorted(CANONICAL_SYMPTOMS))
    return SYSTEM_PROMPT.format(symptom_list=names)


# --------------------------------------------------------------------------
# 合併：安全優先
# --------------------------------------------------------------------------
def merge_facts(
    keyword_facts: Dict[str, Any], llm: LLMStructuredSymptoms
) -> Dict[str, Any]:
    """把已驗證的 LLM 結果併入詞典 facts。

    詞典命中永遠保留；LLM 只能新增或在缺值處補齊；紅旗相關欄位衝突時取較安全值。
    """
    facts = dict(keyword_facts)
    notes: List[str] = []

    # 1) 症狀：聯集，詞典結果排在前面（保留原順序語意）
    kw_symptoms: List[str] = list(facts.get("symptoms") or [])
    added = [s for s in llm.symptoms if s not in kw_symptoms]
    if added:
        facts["symptoms"] = kw_symptoms + added
        notes.append(f"LLM 新增症狀: {', '.join(added)}")

    # 2) species：詞典為 unknown 時才採用 LLM；有值時衝突不改（不放寬）
    if llm.species is not None and llm.species != Species.UNKNOWN:
        current = facts.get("species")
        if current in (None, "unknown", Species.UNKNOWN):
            facts["species"] = llm.species.value
            notes.append(f"LLM 補齊物種: {llm.species.value}")
        elif current != llm.species.value:
            notes.append(
                f"物種衝突（詞典 {current} vs LLM {llm.species.value}）→ 保留詞典結果"
            )

    # 3) 純數值欄位：只在詞典缺值時補齊，不覆寫
    for field in ("body_weight_kg", "body_size", "age_months", "sex", "duration_hours", "temperature_c"):
        val = getattr(llm, field, None)
        if val is not None and facts.get(field) is None:
            # 規則引擎以字串比對列舉值（op: eq / in），存入 Enum 會比不中。
            facts[field] = val.value if isinstance(val, BodySize) else val
            notes.append(f"LLM 補齊 {field}")

    # 4) 紅旗相關布林欄位：衝突時取較危險的值
    for field in SAFER_BOOL_FALSE:
        llm_val = getattr(llm, field, None)
        if llm_val is None:
            continue
        cur = facts.get(field)
        if cur is None:
            facts[field] = llm_val
            notes.append(f"LLM 補齊 {field}={llm_val}")
        elif cur != llm_val:
            # False 較危險 → 取 False
            facts[field] = False
            notes.append(f"{field} 衝突 → 取較安全（較保守）的 False")

    for field in SAFER_BOOL_TRUE:
        llm_val = getattr(llm, field, None)
        if llm_val is None:
            continue
        cur = facts.get(field)
        if cur is None:
            facts[field] = llm_val
            notes.append(f"LLM 補齊 {field}={llm_val}")
        elif cur != llm_val:
            # True 較危險 → 取 True
            facts[field] = True
            notes.append(f"{field} 衝突 → 取較安全（較保守）的 True")

    # 5) mentation：取較嚴重者
    if llm.mentation is not None:
        cur = facts.get("mentation")
        llm_sev = MENTATION_SEVERITY.get(llm.mentation.value, 1)
        cur_sev = MENTATION_SEVERITY.get(cur or "unknown", 1) if cur else -1
        if cur is None:
            facts["mentation"] = llm.mentation.value
            notes.append(f"LLM 補齊精神狀態: {llm.mentation.value}")
        elif llm_sev > cur_sev:
            facts["mentation"] = llm.mentation.value
            notes.append(
                f"精神狀態衝突（詞典 {cur} vs LLM {llm.mentation.value}）→ 取較嚴重者"
            )

    facts["_llm_structuring"] = {
        "applied": True,
        "notes": notes,
    }
    return facts


# --------------------------------------------------------------------------
# 對外入口
# --------------------------------------------------------------------------
def extract(
    text: str, client: Optional[LLMClient] = None
) -> Optional[LLMStructuredSymptoms]:
    """呼叫 LLM 抽取並通過 schema 驗證；任何失敗回傳 None。"""
    if not text or not text.strip():
        return None
    c = client or get_client()
    raw = c.complete_json(
        system=_build_system_prompt(),
        user=text.strip(),
        max_tokens=600,
    )
    if raw is None:
        return None
    return validate(raw)


def validate(raw: Any) -> Optional[LLMStructuredSymptoms]:
    """把任意 LLM 輸出驗證成 schema；不合法回傳 None（呼叫端退回詞典）。"""
    if not isinstance(raw, dict):
        log.warning("[llm] 結構化輸出不是 JSON 物件，已作廢")
        return None
    # 丟掉值為 None 的鍵，讓 extra=forbid 不會被 null 欄位干擾
    cleaned = {k: v for k, v in raw.items() if v is not None}
    try:
        return LLMStructuredSymptoms.model_validate(cleaned)
    except ValidationError as exc:
        log.warning("[llm] 結構化輸出未通過 schema 驗證，已作廢: %s", exc.errors()[:3])
        return None


def structure_case_llm(
    req: ConsultRequest,
    *,
    client: Optional[LLMClient] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """症狀結構化的 LLM 輔助版本。

    無論 LLM 成功與否，回傳的 facts 形狀都與 `structure_case` 完全一致，
    因此下游閘門程式碼不需要任何分支。

    force=True 時忽略功能旗標（測試用）。
    """
    # 1) 永遠先跑確定性詞典 —— 它是 baseline，也是 LLM 失敗時的完整結果
    facts = structure_case(req)

    if not force and not structuring_enabled():
        return facts

    c = client or get_client()
    if not force and not c.available:
        return facts

    extracted = extract(req.text or "", client=c)
    if extracted is None:
        # 無金鑰、逾時、API 錯誤或 schema 驗證失敗 → 純詞典結果
        return facts

    merged = merge_facts(facts, extracted)

    # 2) 明確給定的請求欄位永遠優先於任何抽取結果（含 LLM）
    #    這與 structure_case 的既有語意一致。
    for field in (
        "species", "body_weight_kg", "body_size", "age_months", "sex", "duration_hours",
        "severity", "can_urinate", "vomiting", "mentation",
        "temperature_c", "can_keep_water",
    ):
        explicit = getattr(req, field, None)
        if explicit is None:
            continue
        merged[field] = explicit.value if hasattr(explicit, "value") else explicit

    return merged


__all__ = [
    "LLMStructuredSymptoms",
    "structure_case_llm",
    "merge_facts",
    "validate",
    "extract",
    "CANONICAL_SYMPTOMS",
]
