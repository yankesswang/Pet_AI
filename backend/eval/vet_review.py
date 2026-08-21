"""VetLink AI — 獸醫盲審工作流 (clinical blind review)。

為什麼需要這一份，而不是再多寫一百條自製測試：

  自動指標只能量「系統有沒有照規則做」。它無法回答臨床問題 ——
  這個分級對嗎？這段衛教在這個情境下說得對嗎？主張真的被來源支持嗎？

  目前的「主張引用正確率 100%」是**建構上必然**的結果：主張直接取自
  已審核段落原文，所以「有沒有來源」幾乎不可能失敗。它證明的是綁定完整性，
  不是獸醫認定的語意正確。把它當成臨床證據會誤導評審。

因此三層指標必須分開陳述：

  自動指標   主張—段落綁定完整率     由 eval/run_eval.py 產出（本檔不涉入）
  人工指標   獸醫語意支持率           本檔：獸醫逐項判斷主張是否被來源支持
  臨床指標   與獸醫共識分級一致率     本檔：與兩名獸醫的共識分級比對

用法：

    # 1. 抽樣並產生盲審表（不含系統判定，避免定錨）
    python eval/vet_review.py sample --n 40 --out review_sheet.jsonl

    # 2. 獸醫填寫 reviewer_state / claims_supported / notes 後回存

    # 3. 計分（需 ≥2 名獸醫的檔案才能算共識與 Cohen's kappa）
    python eval/vet_review.py score review_a.jsonl review_b.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.holdout import load_holdout  # noqa: E402

STATES = ("RED", "YELLOW", "GREEN", "BLUE")


# --------------------------------------------------------------------------
# 1. 抽樣 — 產生盲審表
# --------------------------------------------------------------------------
def build_sheet(n: int = 40, seed: int = 20260821) -> List[Dict[str, Any]]:
    """抽樣並產生**不含系統判定**的盲審表。

    刻意不放入系統狀態與規則編號：獸醫先獨立判斷，才能量出真正的一致率。
    若讓獸醫看到系統答案再評分，量到的是說服力不是正確率。
    """
    cases = load_holdout()
    rng = random.Random(seed)

    # 依 group 分層抽樣，避免整份都是同一類案例
    by_group: Dict[str, List[Any]] = {}
    for c in cases:
        by_group.setdefault(c.group, []).append(c)

    picked: List[Any] = []
    groups = sorted(by_group)
    per = max(1, n // max(1, len(groups)))
    for g in groups:
        pool = sorted(by_group[g], key=lambda c: c.case_id)
        rng.shuffle(pool)
        picked.extend(pool[:per])
    remaining = [c for c in cases if c not in picked]
    rng.shuffle(remaining)
    picked.extend(remaining[: max(0, n - len(picked))])
    picked = picked[:n]

    sheet: List[Dict[str, Any]] = []
    for c in picked:
        sheet.append(
            {
                "case_id": c.case_id,
                "text": c.text,
                "fields": c.fields,
                # ↓ 獸醫填寫欄位
                "reviewer_id": "",
                "reviewer_state": "",       # RED / YELLOW / GREEN / BLUE
                "claims_supported": None,   # true=主張確實被來源支持
                "clinically_acceptable": None,  # true=此回應臨床上可接受
                "notes": "",
                # 供獸醫覆核依據，不含系統判定
                "basis": c.basis,
            }
        )
    return sheet


# --------------------------------------------------------------------------
# 2. 計分
# --------------------------------------------------------------------------
def _load(path: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rec = json.loads(line)
            out[rec["case_id"]] = rec
    return out


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> Optional[float]:
    """兩名評分者的 Cohen's kappa。無變異時回傳 None。"""
    if not a or len(a) != len(b):
        return None
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    labels = set(a) | set(b)
    expected = sum(
        (sum(1 for x in a if x == lb) / n) * (sum(1 for y in b if y == lb) / n)
        for lb in labels
    )
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def score(paths: List[str]) -> Dict[str, Any]:
    """比對系統判定與獸醫共識分級。

    需要 ≥2 名獸醫：單一評分者無法區分「系統錯」與「這位獸醫的判斷偏好」。
    """
    if len(paths) < 2:
        raise SystemExit(
            "需要至少兩名獸醫的盲審檔案才能計算共識與一致率 —— "
            "單一評分者的分歧無法歸因。"
        )

    sheets = [_load(p) for p in paths]
    common = set(sheets[0])
    for s in sheets[1:]:
        common &= set(s)
    if not common:
        raise SystemExit("這些檔案沒有共同的 case_id，無法比對。")

    from app.api.service import ConsultService
    from app.models import ConsultRequest, Role, Species

    service = ConsultService()

    agreed: List[str] = []          # 獸醫之間有共識的案例
    disagreed: List[str] = []       # 獸醫之間無共識 —— 不計入一致率
    system_match = 0
    semantic_total = 0
    semantic_supported = 0
    rows: List[Dict[str, Any]] = []

    for case_id in sorted(common):
        recs = [s[case_id] for s in sheets]
        states = [(r.get("reviewer_state") or "").upper() for r in recs]
        if any(st not in STATES for st in states):
            continue  # 尚未填寫完成

        fields = dict(recs[0].get("fields") or {})
        species = fields.pop("species", None)
        req = ConsultRequest(
            text=recs[0]["text"],
            role=Role.OWNER,
            species=Species(species) if species else None,
            **fields,
        )
        resp = service.consult(req, vet_verified=False, owner_authorized=False)
        sys_state = resp.state.value

        if len(set(states)) == 1:
            agreed.append(case_id)
            consensus = states[0]
            matched = sys_state == consensus
            system_match += int(matched)
        else:
            disagreed.append(case_id)
            consensus = None
            matched = None

        for r in recs:
            if r.get("claims_supported") is not None:
                semantic_total += 1
                semantic_supported += int(bool(r["claims_supported"]))

        rows.append(
            {
                "case_id": case_id,
                "system_state": sys_state,
                "reviewer_states": states,
                "consensus": consensus,
                "system_matches_consensus": matched,
            }
        )

    kappa = None
    if len(sheets) == 2:
        pairs = [
            (sheets[0][c].get("reviewer_state", "").upper(),
             sheets[1][c].get("reviewer_state", "").upper())
            for c in sorted(common)
            if sheets[0][c].get("reviewer_state") and sheets[1][c].get("reviewer_state")
        ]
        if pairs:
            kappa = cohens_kappa([p[0] for p in pairs], [p[1] for p in pairs])

    return {
        "reviewers": len(paths),
        "cases_reviewed": len(rows),
        "consensus_cases": len(agreed),
        "no_consensus_cases": len(disagreed),
        "inter_rater_kappa": round(kappa, 3) if kappa is not None else None,
        # 臨床指標：與獸醫共識分級一致率
        "consensus_agreement_rate": (
            round(100.0 * system_match / len(agreed), 2) if agreed else None
        ),
        # 人工指標：獸醫語意支持率
        "vet_semantic_support_rate": (
            round(100.0 * semantic_supported / semantic_total, 2)
            if semantic_total else None
        ),
        "rows": rows,
        "caveats": [
            "本結果只在獸醫實際填寫後才有意義；未填寫的案例不計入。",
            "與自動指標「主張—段落綁定完整率」量的不是同一件事，不可互相取代。",
            "無共識案例不計入一致率，但必須逐案討論後才可宣稱臨床有效性。",
        ],
    }


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="獸醫盲審工作流")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("sample", help="產生盲審表")
    s1.add_argument("--n", type=int, default=40)
    s1.add_argument("--out", default="vet_review_sheet.jsonl")

    s2 = sub.add_parser("score", help="計分（需 ≥2 名獸醫的檔案）")
    s2.add_argument("paths", nargs="+")

    args = ap.parse_args()

    if args.cmd == "sample":
        sheet = build_sheet(args.n)
        with open(args.out, "w", encoding="utf-8") as fh:
            for row in sheet:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"已產生 {len(sheet)} 例盲審表: {args.out}")
        print("請獸醫填寫 reviewer_id / reviewer_state / claims_supported 後回存。")
    else:
        print(json.dumps(score(args.paths), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
