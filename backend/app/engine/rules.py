"""VetLink AI — 規則引擎 (提案 §7.1 紅旗規則引擎 / §13.1 獸醫安全規則層).

規則是資料 (YAML)，不是硬編碼的 if。本模組只負責：
  1. 載入並驗證規則包
  2. 針對已結構化的案例欄位，以確定性方式評估條件樹
  3. 回報哪些規則成立、哪些未成立、哪些因缺資料而無法判定

絕對不呼叫 LLM。
"""
from __future__ import annotations

import glob
import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import yaml

RULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules")

# 條件評估的三值邏輯
TRUE = "true"
FALSE = "false"
UNKNOWN = "unknown"  # 缺少必要欄位，無法判定


@dataclass
class Rule:
    rule_id: str
    version: str
    scenario: str
    severity: str
    title: str
    species: List[str]
    presentations: List[str]
    required_questions: List[Dict[str, str]]
    red_flag_conditions: List[Any]
    system_action: str
    allowed_outputs: List[str]
    forbidden_outputs: List[str]
    owner_message: str
    regression_cases: List[str]
    pack_id: str
    pack_version: str
    review_status: str
    reviewed_at: str
    next_review_at: str
    reviewer: str
    clinical_basis: List[str] = field(default_factory=list)

    @property
    def is_red(self) -> bool:
        return self.severity == "red"

    def applies_to_species(self, species: Optional[str]) -> bool:
        if not self.species:
            return True
        if species is None or species == "unknown":
            # 物種未知時，物種特定規則不主動成立，但 unknown 明列者例外
            return "unknown" in self.species
        return species in self.species


@dataclass
class RuleEvaluation:
    rule: Rule
    outcome: str  # fired | not_fired | evaluated_missing_data
    detail: str = ""
    matched_conditions: List[str] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)  # 供產生人類可讀說明


class RuleValidationError(ValueError):
    pass


# --------------------------------------------------------------------------
# 條件評估
# --------------------------------------------------------------------------
def _norm_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _eval_leaf(cond: Dict[str, Any], facts: Dict[str, Any]) -> Tuple[str, str]:
    """評估單一葉節點條件，回傳 (三值結果, 說明)。"""
    field_name = cond.get("field")
    op = cond.get("op")
    expected = cond.get("value")

    if field_name is None or op is None:
        raise RuleValidationError(f"條件缺少 field/op: {cond!r}")

    actual = facts.get(field_name, None)

    # `in [unknown, null]` 這類條件本身就是在檢查缺值，需特別處理
    if op == "in":
        expected_list = _norm_list(expected)
        allows_null = any(e is None or e == "null" for e in expected_list)
        if actual is None:
            result = TRUE if allows_null else UNKNOWN
            return result, f"{field_name}=None in {expected_list} -> {result}"
        hit = actual in expected_list
        return (TRUE if hit else FALSE), f"{field_name}={actual!r} in {expected_list} -> {hit}"

    if actual is None:
        return UNKNOWN, f"{field_name} 缺值，無法判定 {op}"

    if op == "eq":
        hit = actual == expected
        return (TRUE if hit else FALSE), f"{field_name}={actual!r} eq {expected!r} -> {hit}"

    if op == "ne":
        hit = actual != expected
        return (TRUE if hit else FALSE), f"{field_name}={actual!r} ne {expected!r} -> {hit}"

    if op in ("gte", "lte", "gt", "lt"):
        try:
            a = float(actual)
            b = float(expected)
        except (TypeError, ValueError):
            return UNKNOWN, f"{field_name}={actual!r} 非數值，無法比較"
        hit = {
            "gte": a >= b,
            "lte": a <= b,
            "gt": a > b,
            "lt": a < b,
        }[op]
        return (TRUE if hit else FALSE), f"{field_name}={a} {op} {b} -> {hit}"

    if op == "contains_any":
        haystack = _norm_list(actual)
        needles = _norm_list(expected)
        matched = [n for n in needles if _contains(haystack, n)]
        hit = bool(matched)
        return (TRUE if hit else FALSE), f"{field_name} contains_any {matched or needles} -> {hit}"

    if op == "contains_all":
        haystack = _norm_list(actual)
        needles = _norm_list(expected)
        hit = all(_contains(haystack, n) for n in needles)
        return (TRUE if hit else FALSE), f"{field_name} contains_all {needles} -> {hit}"

    raise RuleValidationError(f"不支援的運算子: {op}")


def _contains(haystack: List[Any], needle: Any) -> bool:
    """比對症狀清單。支援子字串比對，讓「反覆進出砂盆」能命中原句片語。"""
    for item in haystack:
        if item == needle:
            return True
        if isinstance(item, str) and isinstance(needle, str):
            if needle in item or item in needle:
                return True
    return False


def _eval_node(node: Any, facts: Dict[str, Any], trace: List[str]) -> str:
    """遞迴評估條件樹，回傳三值結果。"""
    if isinstance(node, list):
        # 頂層清單 = OR (任一條件成立即紅旗)
        return _eval_any(node, facts, trace)

    if not isinstance(node, dict):
        raise RuleValidationError(f"條件節點格式錯誤: {node!r}")

    if "all_of" in node:
        return _eval_all(node["all_of"], facts, trace)
    if "any_of" in node:
        return _eval_any(node["any_of"], facts, trace)
    if "none_of" in node:
        inner = _eval_any(node["none_of"], facts, trace)
        if inner == TRUE:
            return FALSE
        if inner == FALSE:
            return TRUE
        return UNKNOWN

    result, detail = _eval_leaf(node, facts)
    trace.append(detail)
    return result


def _eval_all(nodes: List[Any], facts: Dict[str, Any], trace: List[str]) -> str:
    results = [_eval_node(n, facts, trace) for n in nodes]
    if any(r == FALSE for r in results):
        return FALSE
    if any(r == UNKNOWN for r in results):
        return UNKNOWN
    return TRUE


def _eval_any(nodes: List[Any], facts: Dict[str, Any], trace: List[str]) -> str:
    results = [_eval_node(n, facts, trace) for n in nodes]
    if any(r == TRUE for r in results):
        return TRUE
    if any(r == UNKNOWN for r in results):
        return UNKNOWN
    return FALSE


# --------------------------------------------------------------------------
# 規則庫
# --------------------------------------------------------------------------
REQUIRED_RULE_FIELDS = (
    "rule_id",
    "version",
    "scenario",
    "severity",
    "title",
    "species",
    "system_action",
    "allowed_outputs",
    "forbidden_outputs",
)


class RuleEngine:
    """載入並評估獸醫安全規則。"""

    def __init__(self, rules_dir: str = RULES_DIR):
        self.rules_dir = rules_dir
        self.rules: List[Rule] = []
        self.packs: Dict[str, Dict[str, Any]] = {}
        self._load()

    # -- 載入 ------------------------------------------------------------
    def _load(self) -> None:
        paths = sorted(glob.glob(os.path.join(self.rules_dir, "*.yaml")))
        paths += sorted(glob.glob(os.path.join(self.rules_dir, "*.yml")))
        if not paths:
            raise RuleValidationError(f"規則目錄沒有任何規則檔: {self.rules_dir}")

        seen_ids = set()
        for path in paths:
            with open(path, "r", encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
            meta = doc.get("meta") or {}
            pack_id = meta.get("pack_id") or os.path.splitext(os.path.basename(path))[0]
            self.packs[pack_id] = meta

            for raw in doc.get("rules") or []:
                for required in REQUIRED_RULE_FIELDS:
                    if required not in raw:
                        raise RuleValidationError(
                            f"{path} 規則 {raw.get('rule_id')} 缺少必要欄位 {required}"
                        )
                rid = raw["rule_id"]
                if rid in seen_ids:
                    raise RuleValidationError(f"重複的 rule_id: {rid}")
                seen_ids.add(rid)

                self.rules.append(
                    Rule(
                        rule_id=rid,
                        version=str(raw["version"]),
                        scenario=raw["scenario"],
                        severity=raw["severity"],
                        title=raw["title"],
                        species=list(raw.get("species") or []),
                        presentations=list(raw.get("presentations") or []),
                        required_questions=list(raw.get("required_questions") or []),
                        red_flag_conditions=raw.get("red_flag_conditions") or [],
                        system_action=raw["system_action"],
                        allowed_outputs=list(raw.get("allowed_outputs") or []),
                        forbidden_outputs=list(raw.get("forbidden_outputs") or []),
                        owner_message=raw.get("owner_message") or "",
                        regression_cases=list(raw.get("regression_cases") or []),
                        pack_id=pack_id,
                        pack_version=str(meta.get("pack_version", "0.0.0")),
                        review_status=meta.get("review_status", "unknown"),
                        reviewed_at=meta.get("reviewed_at", ""),
                        next_review_at=meta.get("next_review_at", ""),
                        reviewer=meta.get("reviewer_placeholder", ""),
                        clinical_basis=list(meta.get("clinical_basis") or []),
                    )
                )

    # -- 查詢 ------------------------------------------------------------
    @property
    def bundle_version(self) -> str:
        """所有規則包版本的確定性指紋，寫入回答護照供 Impact Replay 使用。"""
        parts = sorted(f"{p}:{m.get('pack_version','0')}" for p, m in self.packs.items())
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
        return f"rules-{len(self.rules)}-{digest}"

    def get(self, rule_id: str) -> Optional[Rule]:
        for r in self.rules:
            if r.rule_id == rule_id:
                return r
        return None

    def by_severity(self, severity: str) -> List[Rule]:
        return [r for r in self.rules if r.severity == severity]

    # -- 評估 ------------------------------------------------------------
    def evaluate(
        self,
        facts: Dict[str, Any],
        severities: Optional[List[str]] = None,
    ) -> List[RuleEvaluation]:
        """對所有 (或指定 severity 的) 規則做確定性評估。"""
        out: List[RuleEvaluation] = []
        species = facts.get("species")

        for rule in self.rules:
            if severities is not None and rule.severity not in severities:
                continue
            if not rule.applies_to_species(species):
                out.append(
                    RuleEvaluation(
                        rule=rule,
                        outcome="not_fired",
                        detail=f"物種不適用 (案例={species}, 規則={rule.species})",
                        facts=facts,
                    )
                )
                continue
            if not rule.red_flag_conditions:
                out.append(RuleEvaluation(rule=rule, outcome="not_fired", detail="無觸發條件", facts=facts))
                continue

            trace: List[str] = []
            result = _eval_node(rule.red_flag_conditions, facts, trace)
            outcome = {
                TRUE: "fired",
                FALSE: "not_fired",
                UNKNOWN: "evaluated_missing_data",
            }[result]
            out.append(
                RuleEvaluation(
                    rule=rule,
                    outcome=outcome,
                    detail="; ".join(trace[-4:]) if trace else "",
                    matched_conditions=trace,
                    facts=facts,
                )
            )
        return out

    def fired(self, evaluations: List[RuleEvaluation]) -> List[RuleEvaluation]:
        return [e for e in evaluations if e.outcome == "fired"]

    def required_questions_for(
        self, facts: Dict[str, Any], scenarios: Optional[List[str]] = None
    ) -> List[Dict[str, str]]:
        """依情境彙整必問問題，去重且維持規則順序。"""
        seen = set()
        questions: List[Dict[str, str]] = []
        for rule in self.rules:
            if scenarios and rule.scenario not in scenarios:
                continue
            for q in rule.required_questions:
                key = q.get("field")
                if key and key not in seen:
                    seen.add(key)
                    questions.append({"field": key, "question": q.get("question", ""), "rule_id": rule.rule_id})
        return questions


_ENGINE: Optional[RuleEngine] = None


def get_rule_engine() -> RuleEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RuleEngine()
    return _ENGINE
