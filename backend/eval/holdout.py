"""VetLink AI — 獨立留出測試集載入器 (holdout set)。

與 `eval/case_bank.py` 的差別，以及為什麼需要這一份：

  case_bank 的 177 例是**與規則同源撰寫**的 —— 案例措辭幾乎都直接落在
  `app/engine/structurer.py` 的詞典裡。它證明的是「規則有被正確執行」，
  屬於回歸測試。它無法回答「沒看過的說法會怎樣」，因為每一句都看過。

  holdout 集刻意避開詞典字串，並加入 case_bank 完全沒有的兩類案例：
    * 陰性對照 —— 帶急症詞彙但臨床上不是急症（量測過度警示）
    * 分診邊界 —— 不是分秒必爭但也不該只給衛教（量測不足警示）

因此兩份資料集互補：case_bank 防止退步，holdout 量測有效性。

案例為依公開臨床指南（Merck Veterinary Manual / AAHA / WSAVA）撰寫的
**合成案例，非真實病歷**，標註者非執業獸醫，正式驗證仍需獸醫共識標註。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "holdout_v1.jsonl")

VALID_GROUPS = {
    "red_paraphrase",     # 真急症，用詞典沒收錄的說法描述
    "negative_control",   # 帶急症詞彙但不是急症
    "adversarial",        # 對抗提示：索取劑量／產品／處方
    "insufficient",       # 資訊不足，應只提出必要追問
    "triage_boundary",    # 非急症但需就醫，不得只給居家衛教
}

VALID_STATES = {"RED", "YELLOW", "GREEN", "BLUE"}

# ConsultRequest 允許的欄位（送出前先驗證，避免資料集寫錯欄位名卻靜默忽略）
ALLOWED_FIELDS = {
    "species", "body_weight_kg", "age_months", "sex", "duration_hours",
    "severity", "current_medications", "can_urinate", "vomiting", "mentation",
    "breathing_effort", "mucous_membrane_color", "temperature_c",
    "vomit_count_24h", "can_keep_water",
}


@dataclass
class HoldoutCase:
    case_id: str
    group: str
    text: str
    fields: Dict[str, Any] = field(default_factory=dict)

    # 期望行為（臨床 ground truth，不是系統目前的行為）
    expect_state: Optional[str] = None        # 明確期望狀態；None = 不限定單一狀態
    safe_states: List[str] = field(default_factory=list)  # 可接受的安全結果集合
    require_halt: bool = True                 # 飼主端一律不得進行產品檢索
    require_referral: bool = False            # 回答中必須出現就醫建議
    allow_product: bool = False               # 是否允許輸出產品／劑量（飼主端恆 False）

    perturbation: str = "none"                # 擾動型別（語言／錯字／時態／否定…）
    paraphrase_group: Optional[str] = None    # 同一臨床情境的不同說法，用於一致率
    basis: str = ""                           # 臨床依據
    note: str = ""

    @property
    def is_red_truth(self) -> bool:
        return self.expect_state == "RED"

    @property
    def is_green_truth(self) -> bool:
        return self.expect_state == "GREEN"


def _parse(obj: Dict[str, Any]) -> HoldoutCase:
    expect = obj.get("expect") or {}
    return HoldoutCase(
        case_id=obj["case_id"],
        group=obj["group"],
        text=obj["text"],
        fields=obj.get("fields") or {},
        expect_state=expect.get("state"),
        safe_states=list(expect.get("safe_states") or []),
        require_halt=bool(expect.get("require_halt", True)),
        require_referral=bool(expect.get("require_referral", False)),
        allow_product=bool(expect.get("allow_product", False)),
        perturbation=obj.get("perturbation") or "none",
        paraphrase_group=obj.get("paraphrase_group"),
        basis=obj.get("basis") or "",
        note=obj.get("note") or "",
    )


def load_holdout(path: str = DATA_PATH) -> List[HoldoutCase]:
    """讀取 JSONL 資料集。以 # 開頭的行與空行為註解，會被略過。"""
    cases: List[HoldoutCase] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                cases.append(_parse(json.loads(s)))
            except Exception as exc:  # noqa: BLE001 — 明確指出壞在第幾行
                raise ValueError(f"{path}:{lineno} 無法解析: {exc}") from exc
    return cases


def validate(cases: List[HoldoutCase]) -> List[str]:
    """回傳資料集本身的問題清單（空清單 = 資料集健康）。"""
    problems: List[str] = []
    seen_ids: Dict[str, int] = {}
    seen_texts: Dict[str, str] = {}

    for c in cases:
        if c.case_id in seen_ids:
            problems.append(f"{c.case_id}: case_id 重複")
        seen_ids[c.case_id] = seen_ids.get(c.case_id, 0) + 1

        if c.text.strip() in seen_texts:
            problems.append(f"{c.case_id}: 敘述與 {seen_texts[c.text.strip()]} 完全相同")
        seen_texts[c.text.strip()] = c.case_id

        if c.group not in VALID_GROUPS:
            problems.append(f"{c.case_id}: 未知的 group「{c.group}」")
        if c.expect_state is not None and c.expect_state not in VALID_STATES:
            problems.append(f"{c.case_id}: 未知的 expect.state「{c.expect_state}」")
        if not c.safe_states:
            problems.append(f"{c.case_id}: safe_states 不得為空")
        for s in c.safe_states:
            if s not in VALID_STATES:
                problems.append(f"{c.case_id}: safe_states 含未知狀態「{s}」")
        if c.expect_state and c.expect_state not in c.safe_states:
            problems.append(f"{c.case_id}: expect.state 不在 safe_states 內")
        for k in c.fields:
            if k not in ALLOWED_FIELDS:
                problems.append(f"{c.case_id}: fields 含 ConsultRequest 沒有的欄位「{k}」")
        if not c.basis:
            problems.append(f"{c.case_id}: 缺少 basis（臨床依據），無法供獸醫覆核")

    return problems


def summary(cases: List[HoldoutCase]) -> Dict[str, Any]:
    by_group: Dict[str, int] = {}
    by_perturbation: Dict[str, int] = {}
    for c in cases:
        by_group[c.group] = by_group.get(c.group, 0) + 1
        by_perturbation[c.perturbation] = by_perturbation.get(c.perturbation, 0) + 1
    return {
        "total": len(cases),
        "by_group": dict(sorted(by_group.items())),
        "by_perturbation": dict(sorted(by_perturbation.items())),
        "red_truth": sum(1 for c in cases if c.is_red_truth),
        "green_truth": sum(1 for c in cases if c.is_green_truth),
        "paraphrase_groups": len({c.paraphrase_group for c in cases if c.paraphrase_group}),
    }
