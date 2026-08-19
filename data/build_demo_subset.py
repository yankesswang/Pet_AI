#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_demo_subset.py — VetLink AI 資料層 / Demo 子集建置器

從全量正規化資料挑出一份小而可控的展示子集，供後端 Evidence Gate 直接載入。

輸入: data/processed/drug_evidence.json
輸出: backend/app/data/demo_products.json   （約 150–250 筆產品證據卡）
      backend/app/data/demo_stats.json      （計數與 Demo 場景索引）

挑選策略（依序，先到先得且不重複）
----------------------------------
A. 伴侶動物（犬／貓）且仍有效  —— 獸醫端產品檢索的主力
B. 伴侶動物且已失效            —— **刻意保留**，Demo 必須演示文件效期閘門
                                    真的攔下過期文件，而不是查無資料
C. 中化集團代表品項            —— 集團在公開資料中共 293 張許可證（161 有效／
                                    132 失效），取伴侶動物與有效品項為主的代表
                                    樣本，並保留失效品項；絕不虛構補齊
D. 經濟動物代表（豬／雞／牛…）  —— 少量，展示物種範圍與角色政策邊界
E. 效期不明記錄                —— 少量，展示「資料不完整 -> 不得回答」路徑

排序與抽樣皆以 licence_no 為 key 做決定性排序，確保每次執行結果一致。

用法
----
    python3 build_demo_subset.py
    python3 build_demo_subset.py --target 200
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from typing import Any, Dict, List, Set

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
SRC_PATH = os.path.join(HERE, "processed", "drug_evidence.json")
BACKEND_DATA_DIR = os.path.join(PROJECT_ROOT, "backend", "app", "data")
OUT_PRODUCTS = os.path.join(BACKEND_DATA_DIR, "demo_products.json")
OUT_STATS = os.path.join(BACKEND_DATA_DIR, "demo_stats.json")

DEFAULT_TARGET = 200

# 各配額（總和略大於 target，實際以 target 截斷）
QUOTA_COMPANION_VALID = 110   # A
QUOTA_COMPANION_EXPIRED = 40  # B — 效期閘門的展示素材
QUOTA_LIVESTOCK = 35          # D
QUOTA_UNKNOWN_EXPIRY = 8      # E

QUOTA_CCPC = 45               # C — 中化集團代表品項

# 中化集團的實際登記名稱。經核對原始資料，集團在本資料集共有 293 張許可證：
#   中國化學製藥股份有限公司（及台南官田／台中／新豐等廠）— 284 張
#   中化合成生技股份有限公司山佳工廠                       —   9 張（全數失效）
# 只比對這兩個公司主體，避免「中化」二字誤傷其他業者。
CCPC_COMPANY_PREFIXES = ("中國化學製藥", "中化合成生技")
LIVESTOCK_SPECIES = ("豬", "雞", "牛", "羊", "馬", "魚", "鴨", "火雞")


# ---------------------------------------------------------------------------
# 選取工具
# ---------------------------------------------------------------------------
def sort_key(card: Dict[str, Any]) -> str:
    """決定性排序 key，保證多次執行輸出相同。"""
    return card.get("licence_no", "")


def has_rich_content(card: Dict[str, Any]) -> bool:
    """Demo 卡片需有實質內容才能展示回答護照的主張級引用。"""
    return bool(
        card.get("indications_raw")
        and card.get("ingredients_clean")
        and card.get("name_zh")
    )


def is_ccpc(card: Dict[str, Any]) -> bool:
    """判斷是否為中化集團記錄（以業者名稱主體比對，不用「中化」二字模糊比對）。"""
    company = card.get("company", "")
    return any(company.startswith(p) for p in CCPC_COMPANY_PREFIXES)


def take(
    pool: List[Dict[str, Any]],
    quota: int,
    chosen: Set[str],
    reason: str,
) -> List[Dict[str, Any]]:
    """從 pool 取最多 quota 筆尚未入選的卡片，並標註入選理由。"""
    out: List[Dict[str, Any]] = []
    for card in sorted(pool, key=sort_key):
        if len(out) >= quota:
            break
        lic = card["licence_no"]
        if lic in chosen:
            continue
        chosen.add(lic)
        picked = dict(card)
        picked["demo_selection_reason"] = reason
        out.append(picked)
    return out


# ---------------------------------------------------------------------------
# 主要建置流程
# ---------------------------------------------------------------------------
def build_subset(
    cards: List[Dict[str, Any]], target: int
) -> List[Dict[str, Any]]:
    rich = [c for c in cards if has_rich_content(c)]
    chosen: Set[str] = set()
    selected: List[Dict[str, Any]] = []

    # C. 中化集團代表品項。集團在全量資料中有 293 張許可證（161 有效 / 132 失效），
    #    數量太多不適合全數塞進 Demo，因此依「伴侶動物優先 -> 有效優先」取代表樣本，
    #    並保留少量失效品項作為效期閘門素材。
    ccpc_all = [c for c in cards if is_ccpc(c)]
    ccpc_companion = [
        c for c in ccpc_all if c["is_companion_animal"] and not c["is_expired"]
    ]
    ccpc_valid = [c for c in ccpc_all if not c["is_expired"]]
    ccpc_expired = [c for c in ccpc_all if c["is_expired"]]

    selected += take(ccpc_companion, 20, chosen, "ccpc_companion_valid")
    selected += take(ccpc_valid, 15, chosen, "ccpc_valid")
    selected += take(ccpc_expired, QUOTA_CCPC - 35, chosen, "ccpc_expired")

    # A. 伴侶動物 + 仍有效
    companion_valid = [
        c for c in rich if c["is_companion_animal"] and not c["is_expired"]
    ]
    selected += take(
        companion_valid, QUOTA_COMPANION_VALID, chosen, "companion_valid"
    )

    # B. 伴侶動物 + 已失效（效期閘門展示素材）
    #    兩種失效訊號都必須有素材，因為它們對應不同的閘門判斷路徑：
    #      b1. 帶「(已失效)」標記 —— 來源已明示失效
    #      b2. 僅日期已過         —— 來源沒標記，只能靠民國紀年換算後比對基準日，
    #                                這才是效期閘門真正的價值所在
    companion_expired = [
        c for c in rich if c["is_companion_animal"] and c["is_expired"]
    ]
    marked = [c for c in companion_expired if c["expired_by_marker"]]
    date_only = [
        c for c in companion_expired
        if c["expired_by_date"] and not c["expired_by_marker"]
    ]
    half = QUOTA_COMPANION_EXPIRED // 2
    selected += take(date_only, half, chosen, "companion_expired_date_only")
    selected += take(
        marked, QUOTA_COMPANION_EXPIRED - half, chosen, "companion_expired_marked"
    )
    # 若其中一類素材不足，用另一類補滿配額
    shortfall = QUOTA_COMPANION_EXPIRED - sum(
        1 for c in selected
        if c["demo_selection_reason"].startswith("companion_expired")
    )
    if shortfall > 0:
        selected += take(
            companion_expired, shortfall, chosen, "companion_expired_fill"
        )

    # D. 經濟動物代表：每個物種輪流取，避免全被豬雞佔滿
    livestock_pool = [
        c for c in rich
        if not c["is_companion_animal"]
        and not c["is_expired"]
        and any(s in LIVESTOCK_SPECIES for s in c["species"])
    ]
    per_species = max(1, QUOTA_LIVESTOCK // len(LIVESTOCK_SPECIES))
    livestock: List[Dict[str, Any]] = []
    for species in LIVESTOCK_SPECIES:
        bucket = [c for c in livestock_pool if species in c["species"]]
        livestock += take(bucket, per_species, chosen, f"livestock_{species}")
    # 配額若未滿，從剩餘池補齊
    livestock += take(
        livestock_pool, QUOTA_LIVESTOCK - len(livestock), chosen, "livestock_fill"
    )
    selected += livestock

    # E. 效期不明（展示「資料不完整 -> 拒答」路徑）
    unknown = [c for c in rich if c["expiry_unknown"]]
    selected += take(
        unknown, QUOTA_UNKNOWN_EXPIRY, chosen, "expiry_unknown"
    )

    # 截斷至目標數量，但中化與失效伴侶動物必須保留（Demo 依賴這些）
    if len(selected) > target:
        def must_keep_card(card: Dict[str, Any]) -> bool:
            r = card["demo_selection_reason"]
            return r.startswith("ccpc_") or r.startswith("companion_expired")

        must_keep = [c for c in selected if must_keep_card(c)]
        others = [c for c in selected if not must_keep_card(c)]
        keep_others = others[: max(0, target - len(must_keep))]
        selected = must_keep + keep_others

    selected.sort(key=sort_key)
    return selected


def build_demo_stats(
    subset: List[Dict[str, Any]], full_total: int
) -> Dict[str, Any]:
    species_counts: Dict[str, int] = {}
    reason_counts: Dict[str, int] = {}
    form_counts: Dict[str, int] = {}

    for card in subset:
        for sp in card["species"]:
            species_counts[sp] = species_counts.get(sp, 0) + 1
        r = card["demo_selection_reason"]
        reason_counts[r] = reason_counts.get(r, 0) + 1
        f = card["dosage_form"] or "(未填)"
        form_counts[f] = form_counts.get(f, 0) + 1

    expired = [c for c in subset if c["is_expired"]]
    companion = [c for c in subset if c["is_companion_animal"]]
    ccpc = [c for c in subset if is_ccpc(c)]

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "source_dataset": {
            "name": "農業部動物用藥開放資料",
            "agency": "農業部動植物防疫檢疫署",
            "url": "https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx",
            "full_record_count": full_total,
        },
        "demo_subset_count": len(subset),
        "evaluated_as_of": subset[0]["evaluated_as_of"] if subset else None,

        # Evidence Gate 效期閘門素材
        "expiry_gate": {
            "valid": len(subset) - len(expired),
            "expired": len(expired),
            "expired_by_marker": sum(1 for c in expired if c["expired_by_marker"]),
            "expired_by_date_only": sum(
                1 for c in expired
                if c["expired_by_date"] and not c["expired_by_marker"]
            ),
            "expiry_unknown": sum(1 for c in subset if c["expiry_unknown"]),
        },

        "companion_animal": {
            "total": len(companion),
            "valid": sum(1 for c in companion if not c["is_expired"]),
            "expired": sum(1 for c in companion if c["is_expired"]),
        },

        # 中化集團：僅呈現公開資料實際存在的許可證，不虛構任何品項
        "ccpc_records": {
            "count_in_demo": len(ccpc),
            "valid_in_demo": sum(1 for c in ccpc if not c["is_expired"]),
            "expired_in_demo": sum(1 for c in ccpc if c["is_expired"]),
            "companion_in_demo": sum(
                1 for c in ccpc if c["is_companion_animal"]
            ),
            "licences": [c["licence_no"] for c in ccpc],
            "note": (
                "中化集團（中國化學製藥、中化合成生技）在農業部公開資料中共有 "
                "293 張許可證（161 有效 / 132 失效）。Demo 依伴侶動物與有效期優先"
                "取代表樣本，並刻意保留失效品項以展示效期閘門。"
                "所有欄位皆來自公開資料，未虛構任何品項；"
                "中化內部核准仿單為入圍後的正式介接項目，不在本 Demo 範圍。"
            ),
        },

        "species_counts": dict(
            sorted(species_counts.items(), key=lambda kv: -kv[1])
        ),
        "dosage_forms": dict(
            sorted(form_counts.items(), key=lambda kv: -kv[1])[:12]
        ),
        "selection_reasons": reason_counts,

        # Demo 腳本可直接引用的範例文件
        "demo_hooks": {
            # 來源已明示「(已失效)」
            "expired_marked_examples": [
                {
                    "doc_id": c["doc_id"],
                    "licence_no": c["licence_no"],
                    "name_zh": c["name_zh"],
                    "expiry_date_iso": c["expiry_date_iso"],
                    "expiry_date_raw": c["expiry_date_raw"],
                }
                for c in expired
                if c["is_companion_animal"] and c["expired_by_marker"]
            ][:5],
            # 來源沒標記，只有換算民國紀年後比對基準日才抓得到 —— 閘門的關鍵展示
            "expired_by_date_only_examples": [
                {
                    "doc_id": c["doc_id"],
                    "licence_no": c["licence_no"],
                    "name_zh": c["name_zh"],
                    "expiry_date_iso": c["expiry_date_iso"],
                    "expiry_date_raw": c["expiry_date_raw"],
                }
                for c in expired
                if c["is_companion_animal"]
                and c["expired_by_date"] and not c["expired_by_marker"]
            ][:5],
            "valid_companion_examples": [
                {
                    "doc_id": c["doc_id"],
                    "licence_no": c["licence_no"],
                    "name_zh": c["name_zh"],
                    "expiry_date_iso": c["expiry_date_iso"],
                    "species": c["species"],
                }
                for c in companion if not c["is_expired"]
            ][:5],
        },
        "disclaimer": (
            "本子集僅供 2026 中化智匯盃競賽原型展示，"
            "資料為政府公開資料之擷取與正規化結果，不構成用藥建議。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="建置 Demo 產品證據卡子集")
    parser.add_argument(
        "--target", type=int, default=DEFAULT_TARGET, help="目標筆數（約 150–250）"
    )
    args = parser.parse_args()

    if not os.path.exists(SRC_PATH):
        print(
            f"錯誤: 找不到 {SRC_PATH}；請先執行 python3 normalize.py",
            file=sys.stderr,
        )
        return 1

    with open(SRC_PATH, "r", encoding="utf-8") as fh:
        cards = json.load(fh)

    print("=" * 68)
    print("VetLink AI — Demo 子集建置")
    print(f"來源全量: {len(cards)} 筆")
    print(f"目標筆數: {args.target}")
    print("=" * 68)

    subset = build_subset(cards, args.target)
    stats = build_demo_stats(subset, len(cards))

    os.makedirs(BACKEND_DATA_DIR, exist_ok=True)
    with open(OUT_PRODUCTS, "w", encoding="utf-8") as fh:
        json.dump(subset, fh, ensure_ascii=False, indent=2)
    with open(OUT_STATS, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)

    g = stats["expiry_gate"]
    ca = stats["companion_animal"]
    print(f"\n子集筆數           : {stats['demo_subset_count']}")
    print("\n[效期閘門素材]")
    print(f"  仍有效           : {g['valid']}")
    print(f"  已失效           : {g['expired']}")
    print(f"    ├ (已失效) 標記 : {g['expired_by_marker']}")
    print(f"    └ 僅日期已過    : {g['expired_by_date_only']}")
    print(f"  效期不明         : {g['expiry_unknown']}")
    print("\n[伴侶動物]")
    print(f"  總數 {ca['total']}（有效 {ca['valid']} / 失效 {ca['expired']}）")
    print("\n[中化相關]")
    cc = stats["ccpc_records"]
    print(f"  Demo 收錄 {cc['count_in_demo']} 筆（有效 {cc['valid_in_demo']} / 失效 {cc['expired_in_demo']}）")
    print("\n[物種分布]")
    for sp, n in list(stats["species_counts"].items())[:10]:
        print(f"  {sp:<4} {n}")
    print("\n[入選理由]")
    for r, n in sorted(stats["selection_reasons"].items(), key=lambda kv: -kv[1]):
        print(f"  {r:<24} {n}")
    print("\n輸出:")
    print(f"  {OUT_PRODUCTS}")
    print(f"  {OUT_STATS}")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
